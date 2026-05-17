"""FastAPI SSE stream tests without real LLM or network."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import main as api_main


class FakeRequest:
    def __init__(self, disconnected_after: int | None = None):
        self.calls = 0
        self.disconnected_after = disconnected_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.disconnected_after is not None and self.calls >= self.disconnected_after


def _payload() -> api_main.ResearchStreamRequest:
    return api_main.ResearchStreamRequest(
        ticker="sh600519",
        depth="quick",
        provider="custom",
        model="fake-model",
        base_url="http://fake.local/v1",
        api_key="fake",
    )


async def _collect(chunks):
    out: list[str] = []
    async for chunk in chunks:
        out.append(chunk)
    return out


def _event_data(chunk: str) -> tuple[str, dict]:
    event = ""
    data = ""
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event = line.replace("event:", "", 1).strip()
        if line.startswith("data:"):
            data = line.replace("data:", "", 1).strip()
    return event, json.loads(data)


@pytest.mark.asyncio
async def test_research_stream_success_with_fake_graph(monkeypatch):
    class FakeGraph:
        def __init__(self, config):
            self.config = config

        def run(self, query: str, research_target: str = ""):
            yield {"type": "node", "node": "Portfolio Manager", "output": {"final_decision": "BUY"}, "elapsed": 0.1}

    monkeypatch.setattr(api_main, "ResearchGraph", FakeGraph)

    chunks = await _collect(api_main._research_event_stream(_payload(), FakeRequest()))
    events = [_event_data(c)[0] for c in chunks if c.startswith("event:")]

    assert events == ["start", "agent_step", "complete"]
    assert _event_data(chunks[-1])[1]["final_decision"] == "BUY"


@pytest.mark.asyncio
async def test_research_stream_includes_dashboard_snapshot(monkeypatch):
    dashboard_snapshot = {
        "ticker": "sh600519",
        "code": "600519",
        "updated_at": "2026-05-18T00:00:00",
        "stale": False,
        "source": "agent_snapshot",
        "candles": [{"time": 1704067200, "open": 1, "high": 2, "low": 0.5, "close": 1.5}],
        "metrics": [{"label": "PE", "value": "10.0x", "trend": "flat"}],
        "errors": [],
    }

    class FakeGraph:
        def __init__(self, config):
            self.config = config

        def run(self, query: str, research_target: str = ""):
            yield {
                "type": "node",
                "node": "Fundamentals Analyst",
                "output": {
                    "fundamentals_report": "ok",
                    "dashboard_snapshot": dashboard_snapshot,
                },
                "elapsed": 0.1,
            }

    monkeypatch.setattr(api_main, "ResearchGraph", FakeGraph)

    chunks = await _collect(api_main._research_event_stream(_payload(), FakeRequest()))
    event, data = _event_data(chunks[1])

    assert event == "agent_step"
    assert data["dashboard_snapshot"] == dashboard_snapshot


@pytest.mark.asyncio
async def test_research_stream_error_is_structured(monkeypatch):
    class FakeGraph:
        def __init__(self, config):
            pass

        def run(self, query: str, research_target: str = ""):
            yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(api_main, "ResearchGraph", FakeGraph)

    chunks = await _collect(api_main._research_event_stream(_payload(), FakeRequest()))
    event, data = _event_data(chunks[-1])

    assert event == "error"
    assert data["code"] == "GRAPH_EXECUTION_ERROR"
    assert data["stage"] == "graph"
    assert data["message"] == "boom"
    assert data["recoverable"] is False


@pytest.mark.asyncio
async def test_research_stream_heartbeat_while_waiting(monkeypatch):
    class FakeGraph:
        def __init__(self, config):
            pass

        def run(self, query: str, research_target: str = ""):
            time.sleep(0.03)
            yield {"type": "node", "node": "Portfolio Manager", "output": {"final_decision": "OK"}, "elapsed": 0.1}

    monkeypatch.setenv("OPENFR_SSE_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setattr(api_main, "ResearchGraph", FakeGraph)

    chunks = await _collect(api_main._research_event_stream(_payload(), FakeRequest()))

    assert any(c.startswith(": heartbeat") for c in chunks)
    assert _event_data(chunks[-1])[0] == "complete"


@pytest.mark.asyncio
async def test_research_stream_disconnect_does_not_emit_complete(monkeypatch):
    class FakeGraph:
        def __init__(self, config):
            pass

        def run(self, query: str, research_target: str = ""):
            yield {"type": "node", "node": "Portfolio Manager", "output": {"final_decision": "OK"}, "elapsed": 0.1}

    monkeypatch.setattr(api_main, "ResearchGraph", FakeGraph)

    chunks = await _collect(api_main._research_event_stream(_payload(), FakeRequest(disconnected_after=1)))
    events = [_event_data(c)[0] for c in chunks if c.startswith("event:")]

    assert events == ["start"]
