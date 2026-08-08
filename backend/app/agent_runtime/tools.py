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


OPERATING_TOOLS: dict[str, ToolSpec] = {
    "analyze_revenue": ToolSpec(
        name="analyze_revenue",
        description="Calculate total revenue, order count, average order value, and daily revenue.",
        required_inputs=("orders",),
        runner=lambda context: analyze_revenue(context.orders),
    ),
    "analyze_menu_matrix": ToolSpec(
        name="analyze_menu_matrix",
        description="Classify menu items by sales and gross-profit contribution.",
        required_inputs=("orders", "menu"),
        runner=lambda context: analyze_menu_matrix(context.orders, context.menu),
    ),
    "analyze_review_topics": ToolSpec(
        name="analyze_review_topics",
        description="Count review topics and medium or negative reviews.",
        required_inputs=("reviews",),
        runner=lambda context: analyze_review_topics(context.reviews),
    ),
    "analyze_time_patterns": ToolSpec(
        name="analyze_time_patterns",
        description="Analyze dayparts, revenue trend, and unusual operating days.",
        required_inputs=("orders",),
        runner=lambda context: analyze_time_patterns(context.orders),
    ),
    "analyze_discount_profitability": ToolSpec(
        name="analyze_discount_profitability",
        description="Compare listed prices with receipts and evaluate discount contribution.",
        required_inputs=("orders", "menu"),
        runner=lambda context: analyze_discount_profitability(context.orders, context.menu),
    ),
    "analyze_survival_line": ToolSpec(
        name="analyze_survival_line",
        description="Calculate break-even revenue, projected profit, and cash runway.",
        required_inputs=("orders", "menu", "cost_assumptions"),
        runner=lambda context: analyze_survival_line(
            context.orders, context.menu, context.cost_assumptions or {}
        ),
    ),
    "analyze_channel_profitability": ToolSpec(
        name="analyze_channel_profitability",
        description="Compare dine-in and delivery revenue and contribution profit.",
        required_inputs=("orders", "menu", "cost_assumptions"),
        runner=lambda context: analyze_channel_profitability(
            context.orders, context.menu, context.cost_assumptions or {}
        ),
    ),
}

CORE_OPERATING_TOOLS = (
    "analyze_revenue",
    "analyze_menu_matrix",
    "analyze_review_topics",
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
