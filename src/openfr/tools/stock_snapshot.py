"""Concurrent stock data snapshots for analyst nodes."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any

from langchain_core.tools import BaseTool
from typing_extensions import TypedDict

from openfr.tools import (
    get_stock_financials,
    get_stock_fund_flow,
    get_stock_history,
    get_stock_realtime,
)
from openfr.tools.async_akshare import gather_blocking
from openfr.tools.base import validate_stock_code
from openfr.tools.stock_core import (
    _fetch_roe_revg_profg_fallback,
    _fetch_stock_financial_analysis_indicator,
    _fetch_stock_history,
    _fetch_stock_info,
    _fetch_stock_spot,
    _get_pe_pb_from_spot,
    _norm_code,
    _parse_em_finance_row,
)

_DEFAULT_SNAPSHOT_TIMEOUT = float(os.getenv("OPENFR_STOCK_SNAPSHOT_TIMEOUT", "120"))
_DEFAULT_SNAPSHOT_HISTORY_DAYS = int(os.getenv("OPENFR_SNAPSHOT_HISTORY_DAYS", "60"))


class DashboardCandle(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float


class DashboardMetric(TypedDict, total=False):
    label: str
    value: str
    delta: str
    trend: str
    source: str


class DashboardSnapshot(TypedDict):
    ticker: str
    code: str
    updated_at: str
    stale: bool
    source: str
    candles: list[DashboardCandle]
    metrics: list[DashboardMetric]
    errors: list[str]


def _invoke_tool(tool: BaseTool, args: dict[str, Any]) -> str:
    return str(tool.invoke(args))


def _empty_dashboard_snapshot(symbol: str, code: str | None = None) -> DashboardSnapshot:
    normalized = code or validate_stock_code(symbol)
    return {
        "ticker": symbol,
        "code": normalized,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stale": False,
        "source": "agent_snapshot",
        "candles": [],
        "metrics": [],
        "errors": [],
    }


def _snapshot_calls(
    symbol: str,
    history_days: int,
) -> list[tuple[str, Any, tuple[Any, ...], dict[str, Any]]]:
    """Build the snapshot call list consumed by the bounded AKShare executor."""
    code = validate_stock_code(symbol)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=history_days)).strftime("%Y%m%d")

    return [
        ("realtime", _invoke_tool, (get_stock_realtime, {"symbol": code}), {}),
        (
            "history",
            _invoke_tool,
            (
                get_stock_history,
                {
                    "symbol": code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "period": "daily",
                    "adjust": "qfq",
                },
            ),
            {},
        ),
        ("financials", _invoke_tool, (get_stock_financials, {"symbol": code}), {}),
        ("fund_flow", _invoke_tool, (get_stock_fund_flow, {"symbol": code, "limit": 10}), {}),
        ("dashboard_snapshot", build_dashboard_snapshot, (code, history_days), {}),
    ]


async def _collect_snapshot_results(
    symbol: str,
    history_days: int,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    return await gather_blocking(_snapshot_calls(symbol, history_days), timeout=timeout)


async def collect_stock_snapshot(
    symbol: str,
    history_days: int | None = None,
    timeout: float | None = None,
) -> dict[str, str]:
    """Async entry — runs the blocking snapshot in a worker thread."""
    if timeout is None:
        timeout = _DEFAULT_SNAPSHOT_TIMEOUT
    if history_days is None:
        history_days = _DEFAULT_SNAPSHOT_HISTORY_DAYS
    results = await _collect_snapshot_results(symbol, history_days, timeout)
    return {
        name: _format_snapshot_result(name, item)
        for name, item in results.items()
        if name != "dashboard_snapshot"
    }


async def collect_stock_snapshot_with_dashboard(
    symbol: str,
    history_days: int | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, str], DashboardSnapshot]:
    """Async entry that returns prompt text blocks plus a UI dashboard snapshot."""
    if timeout is None:
        timeout = _DEFAULT_SNAPSHOT_TIMEOUT
    if history_days is None:
        history_days = _DEFAULT_SNAPSHOT_HISTORY_DAYS
    code = validate_stock_code(symbol)
    results = await _collect_snapshot_results(symbol, history_days, timeout)
    text_snapshot = {
        name: _format_snapshot_result(name, item)
        for name, item in results.items()
        if name != "dashboard_snapshot"
    }
    dashboard = _format_dashboard_snapshot_result(
        symbol,
        code,
        results.get("dashboard_snapshot", {}),
    )
    return text_snapshot, dashboard


def collect_stock_snapshot_sync(
    symbol: str,
    history_days: int | None = None,
    timeout: float | None = None,
) -> dict[str, str]:
    """Synchronous bridge for LangGraph nodes (no nested asyncio event loop)."""
    if timeout is None:
        timeout = _DEFAULT_SNAPSHOT_TIMEOUT
    if history_days is None:
        history_days = _DEFAULT_SNAPSHOT_HISTORY_DAYS
    try:
        return asyncio.run(
            collect_stock_snapshot(symbol, history_days=history_days, timeout=timeout)
        )
    except RuntimeError:
        # Future async graph integrations may call this bridge while a loop is already running.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="openfr-snap-bridge") as executor:
            future = executor.submit(
                lambda: asyncio.run(
                    collect_stock_snapshot(symbol, history_days=history_days, timeout=timeout)
                )
            )
            return future.result(timeout=timeout + 5.0)


def collect_stock_snapshot_with_dashboard_sync(
    symbol: str,
    history_days: int | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, str], DashboardSnapshot]:
    """Synchronous bridge that returns text snapshot and structured dashboard data."""
    if timeout is None:
        timeout = _DEFAULT_SNAPSHOT_TIMEOUT
    if history_days is None:
        history_days = _DEFAULT_SNAPSHOT_HISTORY_DAYS
    try:
        return asyncio.run(
            collect_stock_snapshot_with_dashboard(symbol, history_days=history_days, timeout=timeout)
        )
    except RuntimeError:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="openfr-snap-bridge") as executor:
            future = executor.submit(
                lambda: asyncio.run(
                    collect_stock_snapshot_with_dashboard(
                        symbol,
                        history_days=history_days,
                        timeout=timeout,
                    )
                )
            )
            return future.result(timeout=timeout + 5.0)


def format_stock_snapshot(snapshot: dict[str, str]) -> str:
    """Render the concurrent snapshot into compact prompt context."""
    if not snapshot:
        return "并发数据快照为空。"

    titles = {
        "realtime": "实时行情",
        "history": "历史K线",
        "financials": "最新财报摘要",
        "fund_flow": "资金流向",
    }
    blocks = []
    for key in ("realtime", "history", "financials", "fund_flow"):
        if key in snapshot:
            blocks.append(f"### {titles.get(key, key)}\n{snapshot[key]}")
    return "\n\n".join(blocks)


def _format_snapshot_result(name: str, item: dict[str, Any]) -> str:
    error = item.get("error")
    if error:
        return f"{name} 获取失败: {error[:200]}"
    return str(item.get("value") or "")


def _format_dashboard_snapshot_result(
    symbol: str,
    code: str,
    item: dict[str, Any],
) -> DashboardSnapshot:
    value = item.get("value")
    if isinstance(value, dict):
        snapshot = _empty_dashboard_snapshot(symbol, code)
        snapshot.update(value)
        snapshot["ticker"] = str(snapshot.get("ticker") or symbol)
        snapshot["code"] = str(snapshot.get("code") or code)
        snapshot["source"] = "agent_snapshot"
        if not isinstance(snapshot.get("candles"), list):
            snapshot["candles"] = []
        if not isinstance(snapshot.get("metrics"), list):
            snapshot["metrics"] = []
        if not isinstance(snapshot.get("errors"), list):
            snapshot["errors"] = []
        return snapshot
    snapshot = _empty_dashboard_snapshot(symbol, code)
    error = item.get("error")
    if error:
        snapshot["errors"].append(str(error)[:200])
    return snapshot


def build_dashboard_snapshot(symbol: str, history_days: int | None = None) -> DashboardSnapshot:
    """Build a structured UI snapshot from the same data layer used by analyst prefetch."""
    code = validate_stock_code(symbol)
    days = history_days or _DEFAULT_SNAPSHOT_HISTORY_DAYS
    snapshot = _empty_dashboard_snapshot(symbol, code)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    try:
        hist = _fetch_stock_history(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        snapshot["stale"] = bool(getattr(hist, "attrs", {}).get("_openfr_stale"))
        snapshot["candles"] = _history_to_candles(hist)
    except Exception as exc:
        snapshot["errors"].append(f"history: {str(exc)[:160]}")

    snapshot["metrics"] = _build_dashboard_metrics(code, snapshot["errors"])
    return snapshot


def _history_to_candles(hist: Any) -> list[DashboardCandle]:
    if hist is None or getattr(hist, "empty", True):
        return []
    candles: list[DashboardCandle] = []
    for _, row in hist.tail(90).iterrows():
        try:
            candles.append(
                {
                    "time": _to_epoch_seconds(row.get("日期") or row.get("date")),
                    "open": float(row.get("开盘") or row.get("open")),
                    "high": float(row.get("最高") or row.get("high")),
                    "low": float(row.get("最低") or row.get("low")),
                    "close": float(row.get("收盘") or row.get("close")),
                }
            )
        except Exception:
            continue
    return candles


def _to_epoch_seconds(value: Any) -> int:
    s = str(int(value)) if isinstance(value, (int, float)) else str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(s[:10], fmt).timestamp())
        except ValueError:
            continue
    return int(datetime.now().timestamp())


def _build_dashboard_metrics(code: str, errors: list[str]) -> list[DashboardMetric]:
    pe, pb = "N/A", "N/A"
    try:
        pe, pb = _get_pe_pb_from_spot(code)
    except Exception as exc:
        errors.append(f"valuation: {str(exc)[:160]}")

    roe = "N/A"
    try:
        finance = _fetch_stock_financial_analysis_indicator(code)
        if finance is not None and not finance.empty:
            parsed_roe, _rev, _prof = _parse_em_finance_row(finance.iloc[0])
            roe = _fmt_percentish(parsed_roe)
        if roe == "N/A":
            fallback_roe, _rev, _prof = _fetch_roe_revg_profg_fallback(code)
            roe = _fmt_percentish(fallback_roe)
    except Exception as exc:
        errors.append(f"roe: {str(exc)[:160]}")

    market_cap = "N/A"
    try:
        market_cap = _find_market_cap(code)
    except Exception as exc:
        errors.append(f"market_cap: {str(exc)[:160]}")

    return [
        {"label": "PE", "value": _fmt_ratio(pe), "delta": "", "trend": "flat", "source": "agent_snapshot"},
        {"label": "PB", "value": _fmt_ratio(pb), "delta": "", "trend": "flat", "source": "agent_snapshot"},
        {"label": "ROE", "value": roe, "delta": "", "trend": "flat", "source": "agent_snapshot"},
        {"label": "市值", "value": market_cap, "delta": "Agent", "trend": "flat", "source": "agent_snapshot"},
    ]


def _fmt_ratio(value: Any) -> str:
    try:
        f = float(str(value).replace(",", "").replace("倍", ""))
        if f <= 0:
            return "N/A"
        return f"{f:.1f}x"
    except Exception:
        return str(value) if value not in (None, "") else "N/A"


def _fmt_percentish(value: Any) -> str:
    try:
        f = float(str(value).replace("%", "").replace(",", ""))
        return f"{f:.1f}%"
    except Exception:
        return str(value) if value not in (None, "") else "N/A"


def _find_market_cap(code: str) -> str:
    row = None
    try:
        spot = _fetch_stock_spot()
        if spot is not None and not spot.empty:
            code_col = next((c for c in ("代码", "code", "symbol") if c in spot.columns), spot.columns[0])
            mask = spot[code_col].astype(str).apply(lambda x: _norm_code(x) == code)
            if mask.any():
                row = spot.loc[mask].iloc[0]
    except Exception:
        row = None
    if row is not None:
        cap_col = next((c for c in row.index if "总市值" in str(c)), None)
        if cap_col:
            return _fmt_market_cap(row.get(cap_col))
    info = _fetch_stock_info(code)
    if info is not None and not info.empty:
        for _, r in info.iterrows():
            if "总市值" in str(r.get("item", "")):
                return _fmt_market_cap(r.get("value"))
    return "N/A"


def _fmt_market_cap(value: Any) -> str:
    raw = str(value).replace(",", "").strip()
    try:
        f = float(raw)
    except Exception:
        return raw or "N/A"
    if f >= 1e12:
        return f"{f / 1e12:.2f}T"
    if f >= 1e8:
        return f"{f / 1e8:.1f}亿"
    return f"{f:.0f}"
