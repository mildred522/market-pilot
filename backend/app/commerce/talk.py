from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.commerce.contracts import CommerceInteraction, InteractionMode
from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics import ItemLevel, TimeWindow
from app.commerce.providers import CommerceFactProvider
from app.commerce.tools import (
    CommerceToolContext,
    CommerceToolResult,
    execute_commerce_talk_tools,
)


class CommerceTalkIntent(StrEnum):
    SALES = "sales"
    TRENDS = "trends"
    HOT_PRODUCTS = "hot_products"
    MIXED = "mixed"


class CommerceTalkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=2000)
    interaction: CommerceInteraction
    previous_window: TimeWindow
    current_window: TimeWindow
    item_level: ItemLevel = ItemLevel.SKU

    @model_validator(mode="after")
    def require_talk(self) -> "CommerceTalkRequest":
        if self.interaction.mode is not InteractionMode.TALK:
            raise ValueError("commerce talk requests require talk interaction mode")
        return self


class CommerceTalkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "insufficient_data", "tool_failure"]
    intent: CommerceTalkIntent
    selected_tools: tuple[str, ...]
    executions: tuple[CommerceToolResult, ...]
    suggestions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class CommerceTalkService:
    def answer(
        self,
        request: CommerceTalkRequest,
        dataset: CommerceDataset,
        provider: CommerceFactProvider | None = None,
    ) -> CommerceTalkResponse:
        tool_names = route_talk_question(request.question)
        context = CommerceToolContext(
            interaction=request.interaction,
            dataset=dataset,
            previous_window=request.previous_window,
            current_window=request.current_window,
            item_level=request.item_level,
            provider=provider,
        )
        batch = execute_commerce_talk_tools(tool_names, context)
        status = "completed"
        if not batch.executions or all(item.status == "failed" for item in batch.executions):
            status = "tool_failure"
        elif any(item.status == "failed" for item in batch.executions):
            status = "insufficient_data"
        return CommerceTalkResponse(
            status=status,
            intent=_intent_for_tools(tool_names),
            selected_tools=tuple(tool_names),
            executions=batch.executions,
            suggestions=_suggestions_for(request.interaction),
            limitations=_limitations_for(request.interaction, dataset),
        )


QUESTION_TOOL_MARKERS: dict[str, tuple[str, ...]] = {
    "commerce_discover_hot_products": ("热销", "热点", "爆款", "潜力", "选品"),
    "commerce_compare_product_trends": ("趋势", "增长", "下降", "变化", "最近"),
    "commerce_analyze_product_sales": ("销售", "销量", "成交", "商品", "SKU", "品类"),
}


def route_talk_question(question: str) -> list[str]:
    selected = [
        tool_name
        for tool_name, markers in QUESTION_TOOL_MARKERS.items()
        if any(marker.lower() in question.lower() for marker in markers)
    ]
    if not selected:
        selected = ["commerce_analyze_product_sales"]
    return selected[:3]


def _intent_for_tools(tool_names: list[str]) -> CommerceTalkIntent:
    if len(tool_names) > 1:
        return CommerceTalkIntent.MIXED
    if tool_names[0].endswith("trends"):
        return CommerceTalkIntent.TRENDS
    if tool_names[0].endswith("hot_products"):
        return CommerceTalkIntent.HOT_PRODUCTS
    return CommerceTalkIntent.SALES


def _suggestions_for(interaction: CommerceInteraction) -> tuple[str, ...]:
    if interaction.scope.mode.value == "benchmark":
        return ("可将结果作为历史样本案例，不要直接当作当前市场结论。",)
    return ("如需长期目标、行动步骤和复盘条件，请由有权限的用户创建 Plan。",)


def _limitations_for(
    interaction: CommerceInteraction,
    dataset: CommerceDataset,
) -> tuple[str, ...]:
    limitations = ["Talk 只提供只读分析，不会修改数据或执行外部动作。"]
    if interaction.scope.mode.value == "benchmark":
        limitations.append("公开基准数据不代表当前商家的实时经营事实。")
    if dataset.snapshot.capabilities:
        limitations.append("未提供的成本、库存、流量等能力不会被模型补齐。")
    return tuple(limitations)
