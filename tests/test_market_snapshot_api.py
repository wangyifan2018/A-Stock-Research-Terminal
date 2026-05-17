"""Dashboard market snapshot tests without live network access."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import main as api_main


def test_market_snapshot_uses_history_and_real_metrics(monkeypatch):
    history = pd.DataFrame(
        [
            {"日期": "2024-01-02", "开盘": 10.0, "最高": 11.0, "最低": 9.8, "收盘": 10.5},
            {"日期": "2024-01-03", "开盘": 10.5, "最高": 12.0, "最低": 10.2, "收盘": 11.8},
        ]
    )
    finance = pd.DataFrame([{"净资产收益率": 18.2}])
    spot = pd.DataFrame([{"代码": "600519", "总市值": 2_100_000_000_000}])

    monkeypatch.setattr(api_main, "_fetch_stock_history", lambda **_kwargs: history)
    monkeypatch.setattr(api_main, "_get_pe_pb_from_spot", lambda _code: ("24.8", "8.1"))
    monkeypatch.setattr(api_main, "_fetch_stock_financial_analysis_indicator", lambda _code: finance)
    monkeypatch.setattr(api_main, "_parse_em_finance_row", lambda _row: (18.2, None, None))
    monkeypatch.setattr(api_main, "_fetch_stock_spot", lambda: spot)

    snapshot = api_main._build_market_snapshot("sh600519")

    assert snapshot.code == "600519"
    assert len(snapshot.candles) == 2
    assert snapshot.candles[-1].close == 11.8
    assert {metric.label: metric.value for metric in snapshot.metrics} == {
        "PE": "24.8x",
        "PB": "8.1x",
        "ROE": "18.2%",
        "市值": "2.10T",
    }
    assert snapshot.errors == []


def test_market_snapshot_degrades_when_history_fails(monkeypatch):
    def fail_history(**_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(api_main, "_fetch_stock_history", fail_history)
    monkeypatch.setattr(api_main, "_get_pe_pb_from_spot", lambda _code: ("N/A", "N/A"))
    monkeypatch.setattr(api_main, "_fetch_stock_financial_analysis_indicator", lambda _code: pd.DataFrame())
    monkeypatch.setattr(api_main, "_fetch_roe_revg_profg_fallback", lambda _code: (None, None, None))
    monkeypatch.setattr(api_main, "_fetch_stock_spot", lambda: pd.DataFrame())
    monkeypatch.setattr(api_main, "_fetch_stock_info", lambda _code: pd.DataFrame())

    snapshot = api_main._build_market_snapshot("600519")

    assert snapshot.candles == []
    assert snapshot.metrics[0].value == "N/A"
    assert snapshot.metrics[2].value == "N/A"
    assert any(error.startswith("history:") for error in snapshot.errors)
