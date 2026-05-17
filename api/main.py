"""FastAPI entrypoint for streaming OpenFR research events."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from openfr.config import Config, PROVIDER_CONFIG  # noqa: E402
from openfr.graph import ResearchGraph  # noqa: E402
from openfr.tools.base import validate_stock_code  # noqa: E402
from openfr.tools.stock_core import (  # noqa: E402
    _fetch_roe_revg_profg_fallback,
    _fetch_stock_financial_analysis_indicator,
    _fetch_stock_history,
    _fetch_stock_info,
    _fetch_stock_spot,
    _get_pe_pb_from_spot,
    _norm_code,
    _parse_em_finance_row,
)

logger = logging.getLogger(__name__)


app = FastAPI(
    title="OpenFR API",
    description="Streaming API service for OpenFR multi-agent financial research.",
    version="0.1.0",
)

_cors_origins = [
    origin.strip()
    for origin in os.getenv("OPENFR_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


Depth = Literal["quick", "deep"]
Provider = Literal[
    "deepseek",
    "doubao",
    "dashscope",
    "zhipu",
    "modelscope",
    "kimi",
    "stepfun",
    "minimax",
    "openai",
    "anthropic",
    "openrouter",
    "together",
    "groq",
    "ollama",
    "custom",
]


class ResearchStreamRequest(BaseModel):
    """Request body for the SSE research endpoint."""

    ticker: str = Field(..., min_length=1, examples=["sh600519"])
    depth: Depth = Field("quick", description="Research depth: quick or deep.")
    question: str | None = Field(
        default=None,
        description="Optional custom research question. If omitted, OpenFR builds one from ticker/depth.",
    )
    provider: Provider | None = Field(
        default=None,
        description="Optional model provider override. Defaults to OPENFR_PROVIDER/env config.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override, for example deepseek-r1 or Qwen/QwQ-32B.",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional OpenAI-compatible base URL, for vLLM/DeepSeek/local gateways.",
    )
    api_key: str | None = Field(
        default=None,
        description="Optional API key override. Local vLLM can pass any non-empty value.",
    )


class HealthResponse(BaseModel):
    status: str
    service: str


class MarketCandle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float


class MarketMetric(BaseModel):
    label: str
    value: str
    delta: str = ""
    trend: Literal["up", "down", "flat"] = "flat"
    source: str = "akshare"


class MarketSnapshotResponse(BaseModel):
    ticker: str
    code: str
    updated_at: str
    stale: bool = False
    source: str = "akshare"
    candles: list[MarketCandle] = Field(default_factory=list)
    metrics: list[MarketMetric] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


_NODE_META: dict[str, tuple[str, str]] = {
    "Market Analyst": ("data_collection", "正在获取并分析市场行情数据"),
    "Fundamentals Analyst": ("data_collection", "正在获取并分析财务基本面数据"),
    "News Analyst": ("data_collection", "正在获取并分析新闻舆情数据"),
    "Macro Analyst": ("data_collection", "正在获取并分析宏观经济数据"),
    "tools_market": ("tool_call", "正在调用市场数据工具"),
    "tools_fundamentals": ("tool_call", "正在调用财务数据工具"),
    "tools_news": ("tool_call", "正在调用新闻数据工具"),
    "tools_macro": ("tool_call", "正在调用宏观数据工具"),
    "Bull Researcher": ("debate", "正在进行多头分析"),
    "Bear Researcher": ("debate", "正在进行空头分析"),
    "Research Manager": ("synthesis", "正在综合多空辩论并生成投资建议"),
    "Aggressive Analyst": ("risk_analysis", "正在进行激进风险评估"),
    "Conservative Analyst": ("risk_analysis", "正在进行保守风险评估"),
    "Neutral Analyst": ("risk_analysis", "正在进行中性风险评估"),
    "Portfolio Manager": ("final", "正在生成最终研究报告"),
}

_REPORT_FIELDS: dict[str, str] = {
    "market_report": "市场分析报告",
    "fundamentals_report": "财务基本面分析报告",
    "news_report": "新闻舆情分析报告",
    "macro_report": "宏观经济分析报告",
}


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="openfr-api")


@app.get("/api/v1/market/snapshot", response_model=MarketSnapshotResponse)
async def market_snapshot(ticker: str) -> MarketSnapshotResponse:
    """Return real market data for the dashboard's left panels."""

    try:
        return await asyncio.to_thread(_build_market_snapshot, ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Market snapshot endpoint failed")
        code = ticker.strip() or "unknown"
        return MarketSnapshotResponse(
            ticker=ticker,
            code=code,
            updated_at=datetime.now().isoformat(timespec="seconds"),
            source="akshare",
            errors=[f"snapshot: {str(exc)[:160]}"],
        )


@app.post("/api/v1/research/stream")
async def stream_research(payload: ResearchStreamRequest, request: Request) -> StreamingResponse:
    """Stream LangGraph node events as Server-Sent Events."""

    return StreamingResponse(
        _research_event_stream(payload, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _research_event_stream(
    payload: ResearchStreamRequest,
    request: Request,
) -> AsyncIterator[str]:
    start_time = time.perf_counter()

    try:
        query = _build_query(payload)
        config = _build_config(payload)
        heartbeat_seconds = _env_float("OPENFR_SSE_HEARTBEAT_SECONDS", 15.0)

        yield _sse(
            "start",
            {
                "ticker": payload.ticker,
                "depth": payload.depth,
                "query": query,
                "provider": config.provider,
                "model": config.get_model_name(),
                "base_url": config.get_base_url(),
            },
        )

        graph = await asyncio.to_thread(ResearchGraph, config)
        iterator = graph.run(query=query, research_target=payload.ticker)
        final_decision = ""
        completed = False

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("SSE client disconnected before graph completion")
                    return

                next_task = asyncio.create_task(asyncio.to_thread(_next_event, iterator))
                try:
                    while not next_task.done():
                        done, _ = await asyncio.wait({next_task}, timeout=heartbeat_seconds)
                        if done:
                            break
                        if await request.is_disconnected():
                            next_task.cancel()
                            logger.info("SSE client disconnected while waiting for graph node")
                            try:
                                await next_task
                            except asyncio.CancelledError:
                                pass
                            return
                        yield _sse_comment("heartbeat")

                    event = await next_task
                except asyncio.CancelledError:
                    return

                if event is None:
                    completed = True
                    break

                if event.get("type") == "error":
                    yield _sse(
                        "error",
                        _error_payload(
                            event.get("message", "Unknown graph error"),
                            code="GRAPH_EXECUTION_ERROR",
                            stage="graph",
                            recoverable=False,
                        ),
                    )
                    return

                normalized = _normalize_graph_event(event)
                if normalized.get("final_decision"):
                    final_decision = normalized["final_decision"]
                yield _sse("agent_step", normalized)

            if completed:
                yield _sse(
                    "complete",
                    {
                        "ticker": payload.ticker,
                        "elapsed": round(time.perf_counter() - start_time, 3),
                        "final_decision": final_decision,
                    },
                )
        finally:
            _safe_close_iterator(iterator)
    except Exception as exc:
        logger.exception("SSE research stream failed")
        yield _sse(
            "error",
            _error_payload(
                exc,
                code="STREAM_ERROR",
                stage="api",
                recoverable=False,
            ),
        )


def _safe_close_iterator(iterator: Any) -> None:
    """Best-effort shutdown so LangGraph generator stops after client disconnect."""
    close_fn = getattr(iterator, "close", None)
    if not callable(close_fn):
        return
    try:
        close_fn()
    except Exception:
        logger.debug("Research iterator close suppressed", exc_info=True)


def _build_query(payload: ResearchStreamRequest) -> str:
    if payload.question:
        return payload.question

    if payload.depth == "deep":
        return (
            f"请对股票 {payload.ticker} 进行深入投资研究，覆盖行情、财务基本面、新闻舆情、"
            "宏观环境、多空辩论、风险评估，并给出最终投资建议。"
        )

    return (
        f"请对股票 {payload.ticker} 进行快速投资研究，重点覆盖关键行情、核心财务数据、"
        "近期新闻和主要风险，并给出简明投资建议。"
    )


def _build_config(payload: ResearchStreamRequest) -> Config:
    provider = payload.provider or os.getenv("OPENFR_PROVIDER", "zhipu")
    if provider not in PROVIDER_CONFIG:
        provider = "zhipu"

    depth_overrides = _depth_config(payload.depth)
    model = payload.model or os.getenv("OPENFR_MODEL", "")
    base_url = payload.base_url or os.getenv("OPENFR_BASE_URL", "")
    api_key = payload.api_key or os.getenv("OPENFR_API_KEY", "")

    if base_url:
        provider = "custom"
        api_key = api_key or os.getenv("CUSTOM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "") or "EMPTY"
        model = model or os.getenv("CUSTOM_MODEL", "") or os.getenv("OPENFR_MODEL", "") or "deepseek-r1"

    return Config(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=api_key,
        base_url=base_url,
        custom_base_url=base_url,
        custom_api_key=api_key,
        verbose=False,
        **depth_overrides,
    )


def _depth_config(depth: Depth) -> dict[str, int]:
    if depth == "deep":
        return {
            "max_debate_rounds": _env_int("OPENFR_DEEP_MAX_DEBATE_ROUNDS", 2),
            "max_risk_discuss_rounds": _env_int("OPENFR_DEEP_MAX_RISK_ROUNDS", 2),
            "max_recur_limit": _env_int("OPENFR_DEEP_MAX_RECUR_LIMIT", 160),
        }

    return {
        "max_debate_rounds": _env_int("OPENFR_QUICK_MAX_DEBATE_ROUNDS", 1),
        "max_risk_discuss_rounds": _env_int("OPENFR_QUICK_MAX_RISK_ROUNDS", 1),
        "max_recur_limit": _env_int("OPENFR_QUICK_MAX_RECUR_LIMIT", 100),
    }


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer env %s=%r; using default=%s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid float env %s=%r; using default=%s", name, raw, default)
        return default
    return max(0.01, value)


def _build_market_snapshot(ticker: str) -> MarketSnapshotResponse:
    code = validate_stock_code(ticker)
    errors: list[str] = []
    stale = False
    candles: list[MarketCandle] = []

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=_env_int("OPENFR_DASHBOARD_HISTORY_DAYS", 140))).strftime("%Y%m%d")
    try:
        hist = _fetch_stock_history(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        stale = bool(getattr(hist, "attrs", {}).get("_openfr_stale"))
        candles = _history_to_candles(hist)
    except Exception as exc:
        errors.append(f"history: {str(exc)[:160]}")

    metrics = _build_market_metrics(code, errors)
    return MarketSnapshotResponse(
        ticker=ticker,
        code=code,
        updated_at=datetime.now().isoformat(timespec="seconds"),
        stale=stale,
        source="akshare",
        candles=candles,
        metrics=metrics,
        errors=errors,
    )


def _history_to_candles(hist: Any) -> list[MarketCandle]:
    if hist is None or getattr(hist, "empty", True):
        return []
    rows = []
    for _, row in hist.tail(90).iterrows():
        try:
            t = _to_epoch_seconds(row.get("日期") or row.get("date"))
            rows.append(
                MarketCandle(
                    time=t,
                    open=float(row.get("开盘") or row.get("open")),
                    high=float(row.get("最高") or row.get("high")),
                    low=float(row.get("最低") or row.get("low")),
                    close=float(row.get("收盘") or row.get("close")),
                )
            )
        except Exception:
            continue
    return rows


def _to_epoch_seconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        # AKShare sometimes returns Unix-ish timestamps, but date integers are YYYYMMDD.
        s = str(int(value))
    else:
        s = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(s[:10], fmt).timestamp())
        except ValueError:
            continue
    return int(datetime.now().timestamp())


def _build_market_metrics(code: str, errors: list[str]) -> list[MarketMetric]:
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
        MarketMetric(label="PE", value=_fmt_ratio(pe), delta="", trend="flat"),
        MarketMetric(label="PB", value=_fmt_ratio(pb), delta="", trend="flat"),
        MarketMetric(label="ROE", value=roe, delta="", trend="flat"),
        MarketMetric(label="市值", value=market_cap, delta="A-Share", trend="flat"),
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
    # Eastmoney often returns yuan; keep terminal style compact.
    if f >= 1e12:
        return f"{f / 1e12:.2f}T"
    if f >= 1e8:
        return f"{f / 1e8:.1f}亿"
    return f"{f:.0f}"


def _next_event(iterator: Iterator[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def _normalize_graph_event(event: dict[str, Any]) -> dict[str, Any]:
    node_name = event.get("node", "")
    output = event.get("output", {}) or {}
    stage, message = _NODE_META.get(node_name, ("graph", f"正在执行节点: {node_name}"))
    content, content_type = _extract_content(node_name, output)

    normalized: dict[str, Any] = {
        "type": "node",
        "stage": stage,
        "node": node_name,
        "message": message,
        "content_type": content_type,
        "content": content,
        "elapsed": round(float(event.get("elapsed", 0.0)), 3),
        "output": _to_jsonable(_compact_graph_output(output)),
    }

    if node_name == "Portfolio Manager" and isinstance(output, dict):
        normalized["final_decision"] = output.get("final_decision", "")

    if isinstance(output, dict) and output.get("dashboard_snapshot"):
        normalized["dashboard_snapshot"] = output.get("dashboard_snapshot")

    return normalized


def _compact_graph_output(output: Any) -> Any:
    """Strip large duplicate UI payloads from debug output before SSE serialization."""
    if not isinstance(output, dict):
        return output
    return {key: value for key, value in output.items() if key != "dashboard_snapshot"}


def _extract_content(node_name: str, output: Any) -> tuple[str, str]:
    if not isinstance(output, dict):
        return _stringify(output), "raw"

    for field, label in _REPORT_FIELDS.items():
        value = output.get(field)
        if value:
            return _stringify(value), label

    if node_name in ("Bull Researcher", "Bear Researcher"):
        debate_state = output.get("investment_debate_state") or {}
        return _stringify(debate_state.get("current_response", "")), "多空辩论观点"

    if node_name == "Research Manager":
        return _stringify(output.get("investment_plan", "")), "投资建议"

    if node_name in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
        risk_state = output.get("risk_debate_state") or {}
        field_by_node = {
            "Aggressive Analyst": "current_aggressive_response",
            "Conservative Analyst": "current_conservative_response",
            "Neutral Analyst": "current_neutral_response",
        }
        return _stringify(risk_state.get(field_by_node[node_name], "")), "风险评估观点"

    if node_name == "Portfolio Manager":
        return _stringify(output.get("final_decision", "")), "最终研究报告"

    return "", "status"


def _sse(event: str, data: dict[str, Any]) -> str:
    encoded = json.dumps(_to_jsonable(data), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n"


def _sse_comment(comment: str) -> str:
    return f": {comment}\n\n"


def _error_payload(
    exc_or_message: Any,
    *,
    code: str,
    stage: str,
    recoverable: bool,
) -> dict[str, Any]:
    if isinstance(exc_or_message, BaseException):
        message = str(exc_or_message).strip() or type(exc_or_message).__name__
        detail = repr(exc_or_message)
    else:
        message = str(exc_or_message).strip() or "Unknown error"
        detail = message
    return {
        "code": code,
        "message": message,
        "stage": stage,
        "recoverable": recoverable,
        "detail": detail,
    }


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if dataclasses.is_dataclass(value):
        return _to_jsonable(dataclasses.asdict(value))
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _to_jsonable(value.dict())
    if hasattr(value, "content"):
        return _to_jsonable(value.content)
    return str(value)


def _stringify(value: Any) -> str:
    jsonable = _to_jsonable(value)
    if isinstance(jsonable, str):
        return jsonable
    if isinstance(jsonable, list):
        text_blocks = [
            item.get("text", "")
            for item in jsonable
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if text_blocks:
            return "\n".join(text_blocks)
    return json.dumps(jsonable, ensure_ascii=False, indent=2)
