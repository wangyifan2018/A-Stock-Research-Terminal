"""Regression tests for AKShare timeout isolation and snapshot resilience."""

from __future__ import annotations

import asyncio
import time

import pandas as pd

from openfr.tools.async_akshare import gather_blocking
from openfr.tools.cache import stale_cached
from openfr.tools import stock_snapshot
from openfr.tools import stock as stock_tools
from openfr.tools import stock_spot


def test_gather_blocking_preserves_fast_result_when_peer_times_out():
    def fast():
        return "ok"

    def slow():
        time.sleep(0.08)
        return "late"

    async def run():
        return await gather_blocking(
            [
                ("fast", fast, (), {}),
                ("slow", slow, (), {}),
            ],
            timeout=0.02,
        )

    result = asyncio.run(run())

    assert result["fast"] == {"value": "ok", "error": None}
    assert result["slow"]["value"] is None
    assert "timed out" in result["slow"]["error"]


def test_gather_blocking_isolates_exceptions():
    def boom():
        raise ConnectionError("remote closed")

    async def run():
        return await gather_blocking([("boom", boom, (), {})], timeout=1.0)

    result = asyncio.run(run())

    assert result["boom"]["value"] is None
    assert "remote closed" in result["boom"]["error"]


def test_collect_stock_snapshot_sync_formats_successful_slices(monkeypatch):
    def fake_invoke(tool, args):
        return f"{tool.name}:{args['symbol']}"

    monkeypatch.setattr(stock_snapshot, "_invoke_tool", fake_invoke)

    result = stock_snapshot.collect_stock_snapshot_sync("SH600519", timeout=1.0)

    assert result["realtime"].startswith("get_stock_realtime:600519")
    assert result["history"].startswith("get_stock_history:600519")
    assert result["financials"].startswith("get_stock_financials:600519")
    assert result["fund_flow"].startswith("get_stock_fund_flow:600519")


def test_collect_stock_snapshot_sync_keeps_partial_results_on_timeout(monkeypatch):
    def fake_invoke(tool, args):
        if tool.name == "get_stock_history":
            time.sleep(0.08)
            return "late history"
        return f"{tool.name}:ok"

    monkeypatch.setattr(stock_snapshot, "_invoke_tool", fake_invoke)

    result = stock_snapshot.collect_stock_snapshot_sync("600519", timeout=0.02)

    assert result["realtime"] == "get_stock_realtime:ok"
    assert "timed out" in result["history"]
    assert result["financials"] == "get_stock_financials:ok"
    assert result["fund_flow"] == "get_stock_fund_flow:ok"


def test_collect_stock_snapshot_sync_formats_slice_exceptions(monkeypatch):
    def fake_invoke(tool, args):
        if tool.name == "get_stock_fund_flow":
            raise ConnectionError("remote closed")
        return f"{tool.name}:ok"

    monkeypatch.setattr(stock_snapshot, "_invoke_tool", fake_invoke)

    result = stock_snapshot.collect_stock_snapshot_sync("600519", timeout=1.0)

    assert result["realtime"] == "get_stock_realtime:ok"
    assert result["history"] == "get_stock_history:ok"
    assert result["financials"] == "get_stock_financials:ok"
    assert "fund_flow 获取失败" in result["fund_flow"]
    assert "remote closed" in result["fund_flow"]


def test_stock_history_uses_primary_source(monkeypatch):
    primary_df = pd.DataFrame({"日期": ["20240101"], "收盘": [10.0]})

    monkeypatch.setattr(stock_tools, "_fetch_stock_history", lambda **kwargs: primary_df)

    result = stock_tools.get_stock_history.invoke({"symbol": "600519"})

    assert "股票 600519 历史行情" in result
    assert "20240101" in result
    assert "10.0" in result


def test_stock_history_fallback_normalizes_daily_columns(monkeypatch):
    raw_daily = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "open": [9.8],
            "high": [10.2],
            "low": [9.7],
            "close": [10.1],
            "volume": [12345],
        }
    )
    monkeypatch.setattr(stock_spot, "_fetch_stock_history_em", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        stock_spot,
        "_fetch_stock_history_daily",
        lambda **kwargs: stock_spot._normalize_daily_fallback(raw_daily),
    )

    df = stock_spot._fetch_stock_history.__wrapped__(symbol="600519")

    assert list(df.columns) == ["日期", "开盘", "收盘", "最高", "最低", "成交量"]
    assert df.iloc[0]["收盘"] == 10.1


def test_stock_history_all_sources_fail_returns_degraded_message(monkeypatch):
    monkeypatch.setattr(stock_tools, "_fetch_stock_history", lambda **kwargs: pd.DataFrame())

    result = stock_tools.get_stock_history.invoke({"symbol": "600519"})

    assert "未找到股票 600519 的历史数据" in result
    assert "数据源可能临时不可用" in result


def test_hot_stocks_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(stock_tools, "_fetch_hot_stocks", lambda: pd.DataFrame())

    result = stock_tools.get_hot_stocks.invoke({})

    assert result == "暂无热门股票数据"


def test_industry_boards_failure_is_non_fatal(monkeypatch):
    def boom():
        raise ConnectionError("remote closed")

    monkeypatch.setattr(stock_tools, "_fetch_industry_boards", boom)

    result = stock_tools.get_industry_boards.invoke({})

    assert "获取行业板块失败" in result
    assert "稍后重试" in result


def test_stock_history_stale_cache_marker(monkeypatch):
    stale_df = pd.DataFrame({"日期": ["20240103"], "收盘": [11.0]})
    stale_df.attrs["_openfr_stale"] = True

    monkeypatch.setattr(stock_tools, "_fetch_stock_history", lambda **kwargs: stale_df)

    result = stock_tools.get_stock_history.invoke({"symbol": "600519"})

    assert "最近缓存数据" in result
    assert "20240103" in result


def test_stale_cached_returns_stale_dataframe_after_failure():
    calls = {"count": 0}
    cache_key = f"network-resilience-stale-{time.time_ns()}"

    @stale_cached(ttl=0.01, stale_ttl=10.0, key_func=lambda: cache_key)
    def flaky_frame():
        calls["count"] += 1
        if calls["count"] > 1:
            raise ConnectionError("remote closed")
        return pd.DataFrame({"日期": ["20240104"], "收盘": [12.0]})

    fresh = flaky_frame()
    time.sleep(0.02)
    stale = flaky_frame()

    assert not fresh.attrs.get("_openfr_stale")
    assert stale.attrs.get("_openfr_stale") is True
    assert stale.iloc[0]["收盘"] == 12.0
