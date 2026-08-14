from __future__ import annotations

from app.agent_runtime.contracts import AnalysisMode, AgentPlan, PlannedTool
from app.agent_runtime.tools import (
    CORE_OPERATING_TOOLS,
    OperatingToolContext,
    available_tool_specs,
)


FOCUSED_TOOL_MARKERS: dict[str, tuple[str, ...]] = {
    "analyze_revenue": (
        "总营收",
        "营业额",
        "客单价",
        "订单数",
        "营收多少",
        "营收规模",
    ),
    "analyze_menu_matrix": ("菜品", "菜单", "明星", "销量", "毛利"),
    "analyze_review_topics": ("评论", "差评", "顾客反馈", "体验问题"),
    "analyze_time_patterns": (
        "时段",
        "午市",
        "晚市",
        "高峰",
        "趋势",
        "异常日期",
        "营收下降",
    ),
    "analyze_discount_profitability": ("折扣", "优惠", "促销", "满减"),
    "analyze_survival_line": (
        "保本",
        "亏损",
        "现金",
        "支撑",
        "生存",
        "月利润",
        "经营利润",
        "固定成本",
    ),
    "analyze_channel_profitability": (
        "外卖",
        "堂食",
        "渠道",
        "佣金",
        "包材",
        "贡献率",
    ),
}


def apply_operating_plan_policy(
    plan: AgentPlan,
    context: OperatingToolContext,
    *,
    analysis_mode: AnalysisMode,
) -> AgentPlan:
    available = {spec.name for spec in available_tool_specs(context)}
    candidate_by_name: dict[str, PlannedTool] = {}
    for tool in plan.tools:
        if tool.name not in available:
            raise ValueError(f"tool is not allowed: {tool.name}")
        candidate_by_name.setdefault(tool.name, tool)

    if analysis_mode == "focused":
        selected = list(candidate_by_name.values())
        if not 1 <= len(selected) <= 4:
            raise ValueError("focused analysis requires one to four tools")
    else:
        selected = [
            candidate_by_name.get(name)
            or PlannedTool(name=name, reason="required for a complete operating report")
            for name in CORE_OPERATING_TOOLS
            if name in available
        ]

    return plan.model_copy(
        update={"tools": selected, "requires_external_api": False}
    )


def focused_fallback_tools(
    question: str, context: OperatingToolContext
) -> list[PlannedTool]:
    available = {spec.name for spec in available_tool_specs(context)}
    selected = [
        name
        for name in CORE_OPERATING_TOOLS
        if name in available
        and any(marker in question for marker in FOCUSED_TOOL_MARKERS[name])
    ]
    if not selected:
        selected = ["analyze_revenue"] if "analyze_revenue" in available else []
    return [
        PlannedTool(name=name, reason="deterministic question routing")
        for name in selected[:4]
    ]
