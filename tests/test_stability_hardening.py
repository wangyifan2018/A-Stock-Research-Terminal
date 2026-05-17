"""Focused tests for stability hardening helpers."""

from __future__ import annotations

from openfr.agents.utils import tool_executor
from openfr.graph.research_graph import _format_graph_error


class FakeTool:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    def invoke(self, args):
        if self.error:
            raise self.error
        return self.result


def _tool_call(name: str = "fake_tool"):
    return {"name": name, "args": {}, "id": "call-1"}


def test_execute_tool_calls_normalizes_sequential_errors():
    messages = tool_executor.execute_tool_calls(
        [_tool_call()],
        {"fake_tool": FakeTool(error=ConnectionError("remote closed"))},
    )

    assert len(messages) == 1
    assert messages[0].content.startswith("ToolError[fake_tool] elapsed=")
    assert "remote closed" in messages[0].content


def test_tool_timings_is_bounded():
    maxlen = tool_executor.tool_timings.maxlen
    assert maxlen is not None

    for i in range(maxlen + 10):
        tool_executor.tool_timings.append({"tool": f"t{i}", "elapsed": 0.0})

    assert len(tool_executor.tool_timings) == maxlen


def test_format_graph_error_uses_type_for_empty_message():
    assert _format_graph_error(TimeoutError()) == "TimeoutError"
    assert _format_graph_error(RuntimeError("boom")) == "boom"
