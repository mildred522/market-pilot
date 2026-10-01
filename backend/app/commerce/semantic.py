from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.commerce.metrics import ItemLevel


class CommerceMetricCode(StrEnum):
    PRODUCT_SALES = "commerce.product_sales"
    PRODUCT_TRENDS = "commerce.product_trends"
    HOT_PRODUCTS = "commerce.hot_products"


class CommerceMetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CommerceMetricCode
    tool_name: str
    aliases: tuple[str, ...]
    definition: str = Field(min_length=1, max_length=300)
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()


class CommerceQuerySpec(BaseModel):
    """The bounded semantic contract used before selecting a read-only tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_codes: tuple[CommerceMetricCode, ...]
    item_level: ItemLevel
    matched_aliases: tuple[str, ...] = ()
    definitions: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    execution_policy: str = "only registered metrics; parameterized read-only facts"


METRIC_DEFINITIONS: tuple[CommerceMetricDefinition, ...] = (
    CommerceMetricDefinition(
        code=CommerceMetricCode.HOT_PRODUCTS,
        tool_name="commerce_discover_hot_products",
        aliases=("热销", "热点", "爆款", "潜力", "选品"),
        definition="基于当前与基线窗口的销售量、销售额和可复核标签发现历史候选。",
        includes=("历史窗口销售事实", "volume_leader/revenue_leader/momentum 标签"),
        excludes=("利润", "库存", "预测", "因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.PRODUCT_TRENDS,
        tool_name="commerce_compare_product_trends",
        aliases=("趋势", "增长", "下降", "变化", "最近"),
        definition="比较两个等长历史窗口内的商品销售量、销售额和订单变化。",
        includes=("基线窗口", "当前窗口", "商品并集"),
        excludes=("实时行情", "未来预测", "因果效果"),
    ),
    CommerceMetricDefinition(
        code=CommerceMetricCode.PRODUCT_SALES,
        tool_name="commerce_analyze_product_sales",
        aliases=("销售", "销量", "成交", "商品", "SKU"),
        definition="按商品或 SKU 汇总指定历史窗口内的可成交订单商品事实。",
        includes=("paid/fulfilled 订单", "数量", "商品销售额", "去重订单数"),
        excludes=("成本", "利润", "库存", "退款归因"),
    ),
)


def resolve_commerce_query(question: str, *, item_level: ItemLevel) -> CommerceQuerySpec | None:
    normalized = question.lower()
    selected: list[CommerceMetricDefinition] = []
    matched_aliases: list[str] = []
    for definition in METRIC_DEFINITIONS:
        aliases = [alias for alias in definition.aliases if alias.lower() in normalized]
        if aliases:
            selected.append(definition)
            matched_aliases.extend(aliases)
    if not selected:
        return None
    return CommerceQuerySpec(
        metric_codes=tuple(definition.code for definition in selected),
        item_level=item_level,
        matched_aliases=tuple(dict.fromkeys(matched_aliases)),
        definitions=tuple(definition.definition for definition in selected),
        includes=tuple(
            dict.fromkeys(item for definition in selected for item in definition.includes)
        ),
        excludes=tuple(
            dict.fromkeys(item for definition in selected for item in definition.excludes)
        ),
    )


def tool_names_for_query(spec: CommerceQuerySpec) -> list[str]:
    by_code = {definition.code: definition.tool_name for definition in METRIC_DEFINITIONS}
    return [by_code[code] for code in spec.metric_codes]
