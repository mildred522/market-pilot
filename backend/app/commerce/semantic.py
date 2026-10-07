from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.contracts import CommerceAnalysisMode, CommerceInteraction
from app.commerce.metrics import ItemLevel
from app.commerce.metrics import TimeWindow
from app.commerce.snapshot import CommerceSnapshot


SEMANTIC_VERSION = "commerce-semantic-v1"
MAX_QUERY_WINDOW_DAYS = 366


class CommerceMetricCode(StrEnum):
    PRODUCT_SALES = "commerce.product_sales"
    CATEGORY_SALES = "commerce.category_sales"
    CATEGORY_TRENDS = "commerce.category_trends"
    PRODUCT_TRENDS = "commerce.product_trends"
    HOT_PRODUCTS = "commerce.hot_products"


class CommerceMetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CommerceMetricCode
    definition_version: str = SEMANTIC_VERSION
    tool_name: str
    aliases: tuple[str, ...]
    definition: str = Field(min_length=1, max_length=300)
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ("public_dataset", "merchant_upload")
    time_basis: Literal["ordered_at"] = "ordered_at"
    order_statuses: tuple[str, ...] = ("paid", "fulfilled")
    dimensions: tuple[str, ...] = ("item_id", "product_id", "category_name")
    evidence_fields: tuple[str, ...] = (
        "snapshot_id", "window", "order_count", "units_sold", "gross_amount"
    )
    currency_policy: str = "report source currency; do not convert without an explicit rate"


class CommerceQuerySpec(BaseModel):
    """The bounded semantic contract used before selecting a read-only tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_version: str = SEMANTIC_VERSION
    metric_codes: tuple[CommerceMetricCode, ...]
    item_level: ItemLevel
    result_grain: Literal["sku", "product", "category"] = "product"
    matched_aliases: tuple[str, ...] = ()
    definitions: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    execution_policy: str = "only registered metrics; parameterized read-only facts"
    snapshot_id: str | None = None
    scope_mode: CommerceAnalysisMode | None = None
    previous_window: TimeWindow | None = None
    current_window: TimeWindow | None = None
    source_type: str | None = None
    time_basis: str | None = None
    order_statuses: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    evidence_fields: tuple[str, ...] = ()
    currency_policy: str | None = None


METRIC_DEFINITIONS: tuple[CommerceMetricDefinition, ...] = (
    CommerceMetricDefinition(
        code=CommerceMetricCode.HOT_PRODUCTS,
        tool_name="commerce_discover_hot_products",
        aliases=("热销", "热点", "热门", "爆款", "潜力", "选品"),
        definition="基于当前与基线窗口的销售量、销售额和可复核标签发现历史候选。",
        includes=("历史窗口销售事实", "volume_leader/revenue_leader/momentum 标签"),
        excludes=("利润", "库存", "预测", "因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.PRODUCT_TRENDS,
        tool_name="commerce_compare_product_trends",
        aliases=("趋势", "增长", "下降", "变化"),
        definition="比较两个等长历史窗口内的商品销售量、销售额和订单变化。",
        includes=("基线窗口", "当前窗口", "商品并集"),
        excludes=("实时行情", "未来预测", "因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.CATEGORY_TRENDS,
        tool_name="commerce_compare_category_trends",
        aliases=(),
        definition="比较两个等长历史窗口内各品类销售量、销售额和品类内去重订单变化。",
        includes=("基线窗口", "当前窗口", "品类并集"),
        excludes=("跨品类去重订单相加", "利润", "预测", "因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.CATEGORY_SALES,
        tool_name="commerce_analyze_category_sales",
        aliases=("品类", "类目", "分类", "类别"),
        definition="按品类汇总指定历史窗口内可成交订单的商品数量、销量、销售额和去重订单数。",
        includes=("历史窗口销售事实", "品类内去重商品数", "品类内去重订单数"),
        excludes=("利润", "库存", "品类级因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.PRODUCT_SALES,
        tool_name="commerce_analyze_product_sales",
        aliases=("销售", "销量", "成交", "商品", "产品", "货品", "SKU"),
        definition="按商品或 SKU 汇总指定历史窗口内的可成交订单商品事实。",
        includes=("paid/fulfilled 订单", "数量", "商品销售额", "去重订单数"),
        excludes=("成本", "利润", "库存", "退款归因"),
    ),
)


def resolve_commerce_query(question: str, *, item_level: ItemLevel) -> CommerceQuerySpec | None:
    normalized = question.lower()
    if any(
        marker in normalized
        for marker in (
            "品类和商品", "商品和品类", "品类与商品", "商品与品类",
            "品类和sku", "sku和品类",
        )
    ):
        return None
    selected: list[CommerceMetricDefinition] = []
    matched_aliases: list[str] = []
    for definition in METRIC_DEFINITIONS:
        aliases = [alias for alias in definition.aliases if alias.lower() in normalized]
        if aliases:
            selected.append(definition)
            matched_aliases.extend(aliases)
    if not selected:
        return None
    if CommerceMetricCode.CATEGORY_SALES in {definition.code for definition in selected}:
        explicit_trend_aliases = ("趋势", "增长", "下降", "变化")
        if any(alias in normalized for alias in explicit_trend_aliases):
            selected = [next(
                definition for definition in METRIC_DEFINITIONS
                if definition.code is CommerceMetricCode.CATEGORY_TRENDS
            )]
            matched_aliases.extend(alias for alias in explicit_trend_aliases if alias in normalized)
        else:
            selected = [
                definition for definition in selected
                if definition.code is CommerceMetricCode.CATEGORY_SALES
            ]
    return CommerceQuerySpec(
        metric_codes=tuple(definition.code for definition in selected),
        item_level=item_level,
        result_grain=(
            "category"
            if {CommerceMetricCode.CATEGORY_SALES, CommerceMetricCode.CATEGORY_TRENDS}
            & {definition.code for definition in selected}
            else item_level.value
        ),
        matched_aliases=tuple(dict.fromkeys(matched_aliases)),
        definitions=tuple(definition.definition for definition in selected),
        includes=tuple(
            dict.fromkeys(item for definition in selected for item in definition.includes)
        ),
        excludes=tuple(
            dict.fromkeys(item for definition in selected for item in definition.excludes)
        ),
        source_type=None,
        time_basis=_single_definition_value(selected, "time_basis"),
        order_statuses=_common_values(selected, "order_statuses"),
        dimensions=_common_values(selected, "dimensions"),
        evidence_fields=_common_values(selected, "evidence_fields"),
        currency_policy=_single_definition_value(selected, "currency_policy"),
    )


def tool_names_for_query(spec: CommerceQuerySpec) -> list[str]:
    by_code = {definition.code: definition.tool_name for definition in METRIC_DEFINITIONS}
    return [by_code[code] for code in spec.metric_codes]


def bind_commerce_query(
    spec: CommerceQuerySpec,
    *,
    interaction: CommerceInteraction,
    snapshot: CommerceSnapshot,
    previous_window: TimeWindow,
    current_window: TimeWindow,
) -> CommerceQuerySpec:
    """Bind the parsed metric request to the immutable execution scope."""

    validate_commerce_query_scope(
        spec,
        interaction=interaction,
        snapshot=snapshot,
        previous_window=previous_window,
        current_window=current_window,
    )
    return spec.model_copy(
        update={
            "snapshot_id": snapshot.snapshot_id,
            "scope_mode": interaction.scope.mode,
            "source_type": snapshot.source_type,
            "previous_window": previous_window,
            "current_window": current_window,
        }
    )


def validate_commerce_query_scope(
    spec: CommerceQuerySpec,
    *,
    interaction: CommerceInteraction,
    snapshot: CommerceSnapshot,
    previous_window: TimeWindow,
    current_window: TimeWindow,
) -> None:
    if snapshot.state.value != "ready":
        raise ValueError("commerce snapshot is not ready")
    if spec.source_type is not None and spec.source_type != snapshot.source_type:
        raise ValueError("query source type does not match the requested snapshot")
    supported_sources = {
        source_type
        for definition in METRIC_DEFINITIONS
        if definition.code in spec.metric_codes
        for source_type in definition.source_types
    }
    if snapshot.source_type not in supported_sources:
        raise ValueError("query metrics are not supported by this source type")
    if snapshot.mode is not interaction.scope.mode:
        raise ValueError("query scope mode does not match snapshot mode")
    requested_snapshot = interaction.scope.snapshot_id
    if requested_snapshot is not None and requested_snapshot != snapshot.snapshot_id:
        raise ValueError("query snapshot does not match the requested snapshot")
    if previous_window.end > current_window.start:
        raise ValueError("comparison windows must not overlap")
    for name, window in (("previous", previous_window), ("current", current_window)):
        if window.end - window.start > timedelta(days=MAX_QUERY_WINDOW_DAYS):
            raise ValueError(f"{name} query window exceeds the {MAX_QUERY_WINDOW_DAYS}-day budget")
    if any(code in spec.metric_codes for code in (
        CommerceMetricCode.PRODUCT_TRENDS,
        CommerceMetricCode.CATEGORY_TRENDS,
        CommerceMetricCode.HOT_PRODUCTS,
    )):
        if current_window.end - current_window.start != previous_window.end - previous_window.start:
            raise ValueError("trend and hot-product queries require equal-length windows")


def _common_values(
    definitions: list[CommerceMetricDefinition], field: Literal["order_statuses", "dimensions", "evidence_fields"]
) -> tuple[str, ...]:
    values: list[str] = []
    for definition in definitions:
        for value in getattr(definition, field):
            if value not in values:
                values.append(value)
    return tuple(values)


def _single_definition_value(
    definitions: list[CommerceMetricDefinition], field: Literal["time_basis", "currency_policy"]
) -> str:
    values = {str(getattr(definition, field)) for definition in definitions}
    return next(iter(values)) if len(values) == 1 else "mixed"
