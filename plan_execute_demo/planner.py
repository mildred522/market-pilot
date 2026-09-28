from __future__ import annotations

from .models import Plan, PlanItem


TOOL_CATALOG = {
    "revenue": "核算营收、订单量与客单价",
    "menu": "汇总菜品销量、营收与毛利率",
    "survival": "按演示固定成本估算毛利率与保本营收",
}

_FOCUSED_RULES = (
    (("菜品", "菜单", "下架", "爆款", "毛利"), ("menu",)),
    (("保本", "利润", "亏损", "成本", "现金"), ("survival",)),
    (("营收", "营业额", "订单", "客单", "趋势"), ("revenue",)),
)


def build_plan(question: str, mode: str = "focused") -> Plan:
    """Create a deterministic plan; untrusted callers never name Python functions."""
    normalized_mode = mode if mode in {"full", "focused"} else "focused"
    if normalized_mode == "full":
        selected = tuple(TOOL_CATALOG)
        planner = "deterministic-full-policy"
    else:
        selected = _focused_tools(question)
        planner = "deterministic-keyword-policy"
    return Plan(
        mode=normalized_mode,
        question=question,
        planner=planner,
        items=tuple(PlanItem(tool=name, reason=TOOL_CATALOG[name]) for name in selected),
    )


def replan_after_failure(
    plan: Plan, *, completed_tools: set[str], failed_tool: str
) -> Plan | None:
    """Offer one weaker but safe fallback capability, never a retry of the failure."""
    alternatives = {
        "survival": ("revenue",),
        "menu": ("revenue",),
    }
    selected = [
        tool
        for tool in alternatives.get(failed_tool, ())
        if tool not in completed_tools and tool != failed_tool
    ]
    if not selected:
        return None
    return Plan(
        mode=plan.mode,
        question=plan.question,
        planner="one-shot-replan-policy",
        items=tuple(
            PlanItem(
                tool=tool,
                reason=f"{failed_tool} failed; retain only the safe fallback capability",
            )
            for tool in selected
        ),
    )


def _focused_tools(question: str) -> tuple[str, ...]:
    for keywords, selected in _FOCUSED_RULES:
        if any(keyword in question for keyword in keywords):
            return selected
    return ("revenue",)
