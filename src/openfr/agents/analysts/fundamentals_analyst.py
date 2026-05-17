"""
基本面分析师 (Fundamentals Analyst)
"""

from langchain_core.messages import HumanMessage

from openfr.agents.utils.content import extract_text
from openfr.agents.utils.tool_executor import execute_tool_calls
from openfr.tools.stock_snapshot import (
    collect_stock_snapshot_with_dashboard_sync,
    format_stock_snapshot,
)
from openfr.tools import (
    get_stock_financials,
    get_stock_info,
    get_stock_profit_forecast,
    get_stock_fund_flow,
    get_stock_bid_ask,
)

MAX_TOOL_ROUNDS = 2


def create_fundamentals_analyst(llm):
    """创建基本面分析师节点"""

    tools = [
        get_stock_financials,
        get_stock_info,
        get_stock_profit_forecast,
        get_stock_fund_flow,
        get_stock_bid_ask,
    ]
    tools_dict = {tool.name: tool for tool in tools}
    llm_with_tools = llm.bind_tools(tools)

    def fundamentals_analyst_node(state):
        query = state["query"]
        research_target = state.get("research_target", "")
        prefetch_context = ""
        dashboard_snapshot = state.get("dashboard_snapshot", {})
        if research_target:
            snapshot, dashboard_snapshot = collect_stock_snapshot_with_dashboard_sync(research_target)
            prefetch_context = format_stock_snapshot(snapshot)

        system_message = f"""你是基本面分析师。研究标的：{research_target or "待确定"}。问题：{query}

系统已并发预取以下基础数据（实时行情、历史K线、最新财报摘要、资金流向）。请优先使用这些数据撰写报告；只有明显缺失时才补充调用工具。

{prefetch_context or "暂无并发预取数据。"}

**重要：如仍需工具，请在第一次回复时就同时调用所有需要的工具。** 不要分多次调用。

典型操作：同时调用 get_stock_info + get_stock_financials + get_stock_fund_flow 获取数据。

收到工具结果后，直接撰写简洁的基本面分析报告（500字内），包含：公司概况、财务状况、资金流向。不要编造数据。"""

        messages = [HumanMessage(content=f"{system_message}\n\n请开始分析。")]

        # 内部工具调用循环
        for round_num in range(MAX_TOOL_ROUNDS):
            result = llm_with_tools.invoke(messages)
            messages.append(result)

            if not result.tool_calls:
                break

            # 执行工具
            tool_messages = execute_tool_calls(result.tool_calls, tools_dict)
            messages.extend(tool_messages)

        # 提取报告
        report = extract_text(messages[-1].content)
        if report and len(report) > 100:
            return {"fundamentals_report": report, "dashboard_snapshot": dashboard_snapshot}
        return {"fundamentals_report": "", "dashboard_snapshot": dashboard_snapshot}

    return fundamentals_analyst_node
