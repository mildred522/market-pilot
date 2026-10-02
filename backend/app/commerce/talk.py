from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.commerce.contracts import CommerceInteraction, InteractionMode
from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics import ItemLevel, TimeWindow
from app.commerce.providers import CommerceFactProvider
from app.commerce.semantic import (
    CommerceQuerySpec,
    bind_commerce_query,
    resolve_commerce_query,
    tool_names_for_query,
)
from app.commerce.snapshot import CommerceSnapshot
from app.commerce.tools import (
    CommerceToolContext,
    CommerceToolResult,
    execute_commerce_talk_tools,
)


class CommerceTalkIntent(StrEnum):
    UNSUPPORTED = "unsupported"
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
    query_spec: CommerceQuerySpec | None = None
    executions: tuple[CommerceToolResult, ...]
    suggestions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class CommerceTalkService:
    def answer(
        self,
        request: CommerceTalkRequest,
        dataset: CommerceDataset | CommerceSnapshot,
        provider: CommerceFactProvider | None = None,
    ) -> CommerceTalkResponse:
        tool_names = route_talk_question(request.question)
        query_spec = (
            resolve_commerce_query(request.question, item_level=request.item_level)
            if tool_names
            else None
        )
        if not tool_names:
            return CommerceTalkResponse(
                status="insufficient_data",
                intent=CommerceTalkIntent.UNSUPPORTED,
                selected_tools=(),
                query_spec=None,
                executions=(),
                suggestions=("当前仅支持商品销售、趋势和热点问题；请缩小问题范围。",),
                limitations=_limitations_for(request.interaction, dataset),
            )
        snapshot = dataset if isinstance(dataset, CommerceSnapshot) else dataset.snapshot
        try:
            query_spec = bind_commerce_query(
                query_spec,
                interaction=request.interaction,
                snapshot=snapshot,
                previous_window=request.previous_window,
                current_window=request.current_window,
            )
        except ValueError as error:
            return CommerceTalkResponse(
                status="tool_failure",
                intent=_intent_for_tools(tool_names),
                selected_tools=tuple(tool_names),
                query_spec=query_spec,
                executions=(),
                suggestions=("当前查询范围不符合指标执行门禁，请调整时间窗或快照。",),
                limitations=_limitations_for(request.interaction, dataset) + (str(error),),
            )
        context = CommerceToolContext(
            interaction=request.interaction,
            dataset=dataset,
            previous_window=request.previous_window,
            current_window=request.current_window,
            item_level=request.item_level,
            provider=provider,
            query_spec=query_spec,
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
            query_spec=query_spec,
            executions=batch.executions,
            suggestions=_suggestions_for(request.interaction),
            limitations=_limitations_for(request.interaction, dataset),
        )


UNSUPPORTED_QUESTION_MARKERS = (
    "成本", "利润", "毛利", "库存", "实时", "今天", "预测", "未来",
    "投放", "广告", "退款", "退货", "评价", "履约", "物流",
    "品类", "类目",
    "其他项目", "别的项目", "其他店铺", "别的店铺", "其他商家", "别的商家",
)


def route_talk_question(question: str) -> list[str]:
    if any(marker in question for marker in UNSUPPORTED_QUESTION_MARKERS):
        return []
    spec = resolve_commerce_query(question, item_level=ItemLevel.PRODUCT)
    return tool_names_for_query(spec) if spec else []


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
    dataset: CommerceDataset | CommerceSnapshot,
) -> tuple[str, ...]:
    limitations = ["Talk 只提供只读分析，不会修改数据或执行外部动作。"]
    if interaction.scope.mode.value == "benchmark":
        limitations.append("公开基准数据不代表当前商家的实时经营事实。")
    snapshot = dataset if isinstance(dataset, CommerceSnapshot) else dataset.snapshot
    if snapshot.capabilities:
        limitations.append("未提供的成本、库存、流量等能力不会被模型补齐。")
    return tuple(limitations)
