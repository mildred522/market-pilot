from __future__ import annotations

from decimal import Decimal

from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics.contracts import (
    HotProductCandidate,
    ItemLevel,
    TimeWindow,
    TrendComparison,
)
from app.commerce.metrics.sales import compute_sales_report
from app.commerce.metrics.trends import compare_sales_windows


def discover_hot_products(
    dataset: CommerceDataset,
    previous: TimeWindow,
    current: TimeWindow,
    *,
    item_level: ItemLevel = ItemLevel.SKU,
    min_orders: int = 3,
    growth_threshold: Decimal = Decimal("0.25"),
    stable_limit: int = 3,
) -> tuple[HotProductCandidate, ...]:
    current_report = compute_sales_report(dataset, current, item_level=item_level)
    current_by_id = {metric.item_id: metric for metric in current_report.metrics}
    trends = {
        trend.item_id: trend
        for trend in compare_sales_windows(dataset, previous, current, item_level=item_level)
    }
    stable_ids = {
        metric.item_id
        for metric in current_report.metrics[:stable_limit]
        if metric.order_count >= min_orders
    }
    candidates: list[HotProductCandidate] = []
    for item_id, metric in current_by_id.items():
        trend = trends.get(item_id)
        labels: list[str] = []
        evidence: list[str] = []
        if item_id in stable_ids:
            labels.append("stable_best_seller")
            evidence.append(f"current gross amount rank is within top {stable_limit}")
        if metric.order_count < min_orders:
            labels.append("small_sample")
            evidence.append(f"current order count is below {min_orders}")
        if trend and _at_least(trend.gross_amount_growth_rate, growth_threshold):
            labels.append("emerging_product")
            evidence.append(f"gross amount growth is at least {growth_threshold}")
        if trend and _at_most(trend.gross_amount_growth_rate, -growth_threshold):
            labels.append("declining_product")
            evidence.append(f"gross amount growth is at most {-growth_threshold}")
        if not labels:
            continue
        candidates.append(
            HotProductCandidate(
                item_id=item_id,
                product_id=metric.product_id,
                labels=tuple(labels),
                confidence=_confidence(metric.order_count, min_orders),
                current=metric,
                trend=trend,
                evidence=tuple(evidence),
            )
        )
    return tuple(candidates)


def _at_least(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _at_most(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value <= threshold


def _confidence(order_count: int, min_orders: int) -> str:
    if order_count < min_orders:
        return "low"
    if order_count < min_orders * 3:
        return "medium"
    return "high"
