"""工具执行辅助函数"""
import logging
import os
import time
from collections import deque

from langchain_core.messages import ToolMessage

from openfr.tools.parallel import can_parallelize, execute_tools_parallel

logger = logging.getLogger(__name__)

# 全局工具耗时记录，供外部读取；限制长度避免长进程内无限增长。
tool_timings = deque(maxlen=int(os.getenv("OPENFR_TOOL_TIMINGS_MAXLEN", "500")))


def _format_tool_error(tool_name: str, error: object, elapsed: float | None = None) -> str:
    elapsed_part = f" elapsed={elapsed:.3f}s" if elapsed is not None else ""
    message = str(error).strip() or type(error).__name__
    return f"ToolError[{tool_name}]{elapsed_part}: {message}"


def execute_tool_calls(tool_calls, tools_dict):
    """
    执行工具调用列表

    Args:
        tool_calls: LLM 返回的 tool_calls 列表
        tools_dict: {tool_name: tool_function} 字典

    Returns:
        ToolMessage 列表
    """
    results = []
    if can_parallelize(tool_calls):
        t0 = time.perf_counter()
        parallel_results = execute_tools_parallel(
            list(tool_calls),
            tools_dict.get,
            max_workers=int(os.getenv("OPENFR_TOOL_MAX_WORKERS", "3")),
            timeout=float(os.getenv("OPENFR_TOOL_PARALLEL_TIMEOUT", "30")),
        )
        total_elapsed = time.perf_counter() - t0
        logger.debug("[tool] parallel batch %d calls %.3fs", len(tool_calls), total_elapsed)
        for tool_call, result in zip(tool_calls, parallel_results):
            tool_name = tool_call["name"]
            tool_id = tool_call["id"]
            elapsed = result.get("elapsed", total_elapsed)
            tool_timings.append({"tool": tool_name, "elapsed": elapsed})
            if result.get("error"):
                content = _format_tool_error(tool_name, result["error"], elapsed)
            else:
                content = str(result.get("result", ""))
            results.append(ToolMessage(
                content=content,
                tool_call_id=tool_id,
            ))
        return results

    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        if tool_name in tools_dict:
            try:
                t0 = time.perf_counter()
                output = tools_dict[tool_name].invoke(tool_args)
                elapsed = time.perf_counter() - t0
                logger.debug("[tool] %s %.3fs", tool_name, elapsed)
                tool_timings.append({"tool": tool_name, "elapsed": elapsed})
                results.append(ToolMessage(
                    content=str(output),
                    tool_call_id=tool_id,
                ))
            except Exception as e:
                elapsed = time.perf_counter() - t0 if "t0" in locals() else None
                results.append(ToolMessage(
                    content=_format_tool_error(tool_name, e, elapsed),
                    tool_call_id=tool_id,
                ))
        else:
            results.append(ToolMessage(
                content=f"Tool {tool_name} not found",
                tool_call_id=tool_id,
            ))
    return results
