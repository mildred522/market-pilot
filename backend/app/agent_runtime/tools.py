from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.tools.channel_tool import analyze_channel_profitability
from app.tools.discount_tool import analyze_discount_profitability
from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics
from app.tools.survival_tool import analyze_survival_line
from app.tools.time_pattern_tool import analyze_time_patterns


@dataclass(frozen=True)
class OperatingToolContext:
    orders: pd.DataFrame
    menu: pd.DataFrame
    reviews: pd.DataFrame
    cost_assumptions: dict[str, Any] | None = None

    @property
    def available_inputs(self) -> set[str]:
        inputs = {"orders", "menu", "reviews"}
        if self.cost_assumptions is not None:
            inputs.add("cost_assumptions")
        return inputs


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    required_inputs: tuple[str, ...]
    runner: Callable[[OperatingToolContext], dict[str, Any]]
    output_section: str
    use_when: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


OPERATING_TOOLS: dict[str, ToolSpec] = {
    "analyze_revenue": ToolSpec(
        name="analyze_revenue",
        description="计算样本总营收、订单数、客单价和每日营收序列。",
        required_inputs=("orders",),
        runner=lambda context: analyze_revenue(context.orders),
        output_section="revenue",
        use_when=("营收规模", "订单量", "客单价", "每日变化"),
        limitations=("只统计上传订单记录", "缺失日期不会自动补零"),
    ),
    "analyze_menu_matrix": ToolSpec(
        name="analyze_menu_matrix",
        description="按店内销量和毛利率中位数划分菜品经营象限。",
        required_inputs=("orders", "menu"),
        runner=lambda context: analyze_menu_matrix(context.orders, context.menu),
        output_section="menu",
        use_when=("菜品表现", "菜单优化", "销量与毛利"),
        limitations=("象限是店内样本相对分类，不是行业标准",),
    ),
    "analyze_review_topics": ToolSpec(
        name="analyze_review_topics",
        description="按固定关键词统计评论主题，并统计评分不高于 3 分的评论。",
        required_inputs=("reviews",),
        runner=lambda context: analyze_review_topics(context.reviews),
        output_section="reviews",
        use_when=("差评", "顾客反馈", "体验问题"),
        limitations=("基于关键词匹配，不等同于完整情感分析",),
    ),
    "analyze_time_patterns": ToolSpec(
        name="analyze_time_patterns",
        description="分析营业时段、前后半段营收趋势和异常营业日。",
        required_inputs=("orders",),
        runner=lambda context: analyze_time_patterns(context.orders),
        output_section="time_patterns",
        use_when=("时段表现", "营收趋势", "异常日期"),
        limitations=("趋势至少需要 6 个有订单日", "异常识别至少需要 7 个有订单日"),
    ),
    "analyze_discount_profitability": ToolSpec(
        name="analyze_discount_profitability",
        description="根据菜单标价与订单实收差额识别折扣订单并比较利润贡献。",
        required_inputs=("orders", "menu"),
        runner=lambda context: analyze_discount_profitability(context.orders, context.menu),
        output_section="discounts",
        use_when=("折扣", "优惠", "促销利润"),
        limitations=("没有活动 ID 时不能归因到具体优惠", "贡献利润未扣平台与固定成本"),
    ),
    "analyze_survival_line": ToolSpec(
        name="analyze_survival_line",
        description="按样本毛利率和成本假设计算保本线、月利润投影和现金支撑期。",
        required_inputs=("orders", "menu", "cost_assumptions"),
        runner=lambda context: analyze_survival_line(
            context.orders, context.menu, context.cost_assumptions or {}
        ),
        output_section="survival",
        use_when=("保本", "亏损", "现金支撑", "生存风险"),
        limitations=("按样本日均营收外推 30 天", "不是实际财务报表"),
    ),
    "analyze_channel_profitability": ToolSpec(
        name="analyze_channel_profitability",
        description="比较堂食与外卖的营收、直接成本、贡献利润和贡献率。",
        required_inputs=("orders", "menu", "cost_assumptions"),
        runner=lambda context: analyze_channel_profitability(
            context.orders, context.menu, context.cost_assumptions or {}
        ),
        output_section="channels",
        use_when=("外卖", "堂食", "渠道结构", "渠道利润"),
        limitations=("贡献利润未分摊房租、人工等固定成本", "佣金和包材来自用户假设"),
    ),
}

CORE_OPERATING_TOOLS = (
    "analyze_revenue",
    "analyze_menu_matrix",
    "analyze_review_topics",
    "analyze_time_patterns",
    "analyze_discount_profitability",
    "analyze_survival_line",
    "analyze_channel_profitability",
)


def available_tool_specs(context: OperatingToolContext) -> list[ToolSpec]:
    return [
        spec
        for spec in OPERATING_TOOLS.values()
        if set(spec.required_inputs) <= context.available_inputs
    ]


def execute_operating_tools(
    tool_names: list[str], context: OperatingToolContext
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in tool_names:
        spec = OPERATING_TOOLS[name]
        missing = set(spec.required_inputs) - context.available_inputs
        if missing:
            raise ValueError(f"tool {name} is missing inputs: {', '.join(sorted(missing))}")
        results[_result_key(name)] = spec.runner(context)
    return results


def _result_key(tool_name: str) -> str:
    return {
        "analyze_revenue": "revenue",
        "analyze_menu_matrix": "menu",
        "analyze_review_topics": "reviews",
        "analyze_time_patterns": "time_patterns",
        "analyze_discount_profitability": "discounts",
        "analyze_survival_line": "survival",
        "analyze_channel_profitability": "channels",
    }[tool_name]
