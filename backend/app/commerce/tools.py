from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.capabilities import check_capability
from app.commerce.contracts import CommerceCapability, CommerceInteraction, InteractionMode
from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics import (
    ItemLevel,
    TimeWindow,
    compare_sales_windows,
    compute_sales_report,
    discover_hot_products,
)
from app.commerce.providers import CommerceFactProvider, DatasetCommerceFactProvider
from app.commerce.semantic import CommerceQuerySpec, tool_names_for_query
from app.commerce.snapshot import CommerceSnapshot


ToolStatus = Literal["completed", "degraded", "failed"]


class CommerceToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    status: ToolStatus
    data: dict[str, Any] | None = None
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    duration_ms: int = Field(ge=0)


class CommerceToolBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executions: tuple[CommerceToolResult, ...]


@dataclass(frozen=True)
class CommerceToolContext:
    interaction: CommerceInteraction
    dataset: CommerceDataset | CommerceSnapshot
    previous_window: TimeWindow
    current_window: TimeWindow
    item_level: ItemLevel = ItemLevel.SKU
    provider: CommerceFactProvider | None = None
    query_spec: CommerceQuerySpec | None = None

    def validate(self) -> None:
        snapshot = (
            self.dataset
            if isinstance(self.dataset, CommerceSnapshot)
            else self.dataset.snapshot
        )
        if snapshot.mode is not self.interaction.scope.mode:
            raise ValueError("interaction mode does not match snapshot mode")
        if self.interaction.mode is not InteractionMode.TALK:
            raise ValueError("commerce talk tools require talk interaction mode")

    def fact_provider(self) -> CommerceFactProvider:
        if self.provider is not None:
            return self.provider
        if isinstance(self.dataset, CommerceSnapshot):
            raise ValueError("Olist analysis requires a DuckDB fact provider")
        return DatasetCommerceFactProvider(self.dataset)


@dataclass(frozen=True)
class CommerceToolSpec:
    name: str
    description: str
    required_capabilities: frozenset[CommerceCapability]
    runner: Callable[[CommerceToolContext], dict[str, Any]]


def _sales(context: CommerceToolContext) -> dict[str, Any]:
    report = context.fact_provider().sales(
        context.current_window,
        item_level=context.item_level,
    )
    return report.model_dump(mode="json")


def _trends(context: CommerceToolContext) -> dict[str, Any]:
    trends = context.fact_provider().trends(
        context.previous_window,
        context.current_window,
        item_level=context.item_level,
    )
    if isinstance(trends, tuple):
        items = [item.model_dump(mode="json") for item in trends]
    else:
        items = [item.model_dump(mode="json") for item in trends.trends]
    return {
        "previous_window": context.previous_window.model_dump(mode="json"),
        "current_window": context.current_window.model_dump(mode="json"),
        "items": items,
    }


def _hot_products(context: CommerceToolContext) -> dict[str, Any]:
    candidates = context.fact_provider().hot_products(
        context.previous_window,
        context.current_window,
        item_level=context.item_level,
    )
    if isinstance(candidates, tuple):
        items = [candidate.model_dump(mode="json") for candidate in candidates]
    else:
        items = [candidate.model_dump(mode="json") for candidate in candidates.candidates]
    return {
        "mode": context.interaction.scope.mode.value,
        "candidates": items,
    }


COMMERCE_TALK_TOOLS: Mapping[str, CommerceToolSpec] = {
    "commerce_analyze_product_sales": CommerceToolSpec(
        name="commerce_analyze_product_sales",
        description="计算指定快照和时间窗口内的 SKU 或商品销售表现。",
        required_capabilities=frozenset(
            {CommerceCapability.CATALOG, CommerceCapability.SALES}
        ),
        runner=_sales,
    ),
    "commerce_compare_product_trends": CommerceToolSpec(
        name="commerce_compare_product_trends",
        description="比较两个等长度时间窗口内的商品销售趋势。",
        required_capabilities=frozenset(
            {CommerceCapability.CATALOG, CommerceCapability.SALES}
        ),
        runner=_trends,
    ),
    "commerce_discover_hot_products": CommerceToolSpec(
        name="commerce_discover_hot_products",
        description="发现稳定热销、增长潜力、下降和小样本候选。",
        required_capabilities=frozenset(
            {CommerceCapability.CATALOG, CommerceCapability.SALES}
        ),
        runner=_hot_products,
    ),
}


def validate_talk_tool_selection(tool_names: list[str]) -> None:
    unknown = sorted(set(tool_names) - set(COMMERCE_TALK_TOOLS))
    if unknown:
        raise ValueError(f"commerce talk tools are not allowed: {', '.join(unknown)}")


def execute_commerce_talk_tools(
    tool_names: list[str],
    context: CommerceToolContext,
) -> CommerceToolBatch:
    context.validate()
    validate_talk_tool_selection(tool_names)
    if context.query_spec is not None and tool_names != tool_names_for_query(context.query_spec):
        raise ValueError("selected tools do not match the registered query metric codes")
    executions: list[CommerceToolResult] = []
    snapshot = (
        context.dataset
        if isinstance(context.dataset, CommerceSnapshot)
        else context.dataset.snapshot
    )
    available = snapshot.capabilities
    for name in tool_names:
        spec = COMMERCE_TALK_TOOLS[name]
        started = perf_counter()
        missing = [
            capability
            for capability in spec.required_capabilities
            if check_capability(capability, available).status != "supported"
        ]
        if missing:
            executions.append(
                CommerceToolResult(
                    tool_name=name,
                    status="failed",
                    error_code="capability_unavailable",
                    warnings=(
                        "required commerce capabilities are unavailable: "
                        + ", ".join(sorted(item.value for item in missing)),
                    ),
                    duration_ms=_duration_ms(started),
                )
            )
            continue
        try:
            data = spec.runner(context)
            _validate_tool_data(name, data, context)
        except ValueError as error:
            executions.append(
                CommerceToolResult(
                    tool_name=name,
                    status="failed",
                    error_code="invalid_fact_result" if "fact result" in str(error) else "invalid_tool_context",
                    warnings=(str(error),),
                    duration_ms=_duration_ms(started),
                )
            )
            continue
        executions.append(
            CommerceToolResult(
                tool_name=name,
                status="completed",
                data=data,
                evidence=(
                    f"snapshot:{snapshot.snapshot_id}",
                    f"project:{context.interaction.scope.project_id}",
                ),
                duration_ms=_duration_ms(started),
            )
        )
    return CommerceToolBatch(executions=tuple(executions))


def _validate_tool_data(
    tool_name: str,
    data: dict[str, Any],
    context: CommerceToolContext,
) -> None:
    if not isinstance(data, dict):
        raise ValueError("fact result must be an object")
    collection_key = {
        "commerce_analyze_product_sales": "metrics",
        "commerce_compare_product_trends": "items",
        "commerce_discover_hot_products": "candidates",
    }[tool_name]
    rows = data.get(collection_key)
    if not isinstance(rows, list):
        raise ValueError(f"fact result must contain a list of {collection_key}")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("item_id"), str):
            raise ValueError("fact result contains an invalid item row")
        row_level = row.get("item_level")
        if row_level is not None and row_level != context.item_level.value:
            raise ValueError("fact result item level does not match the query")
        if tool_name == "commerce_analyze_product_sales":
            if not isinstance(row.get("product_id"), str):
                raise ValueError("fact result is missing product_id")
            if not isinstance(row.get("units_sold"), (str, int, float)):
                raise ValueError("fact result is missing units_sold")
            if not isinstance(row.get("order_count"), int):
                raise ValueError("fact result is missing order_count")
            if not isinstance(row.get("gross_amount", row.get("item_gross_amount")), (str, int, float)):
                raise ValueError("fact result is missing gross amount")
        elif tool_name == "commerce_compare_product_trends":
            if "current" not in row or "previous" not in row:
                raise ValueError("fact result is missing comparison sides")
        elif tool_name == "commerce_discover_hot_products":
            if not isinstance(row.get("labels"), list) or not isinstance(row.get("current"), dict):
                raise ValueError("fact result is missing hot-product evidence")


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
