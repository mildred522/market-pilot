from __future__ import annotations

from decimal import Decimal

from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics.contracts import (
    ItemLevel,
    ItemSalesMetric,
    TimeWindow,
    TrendComparison,
)
from app.commerce.metrics.sales import compute_sales_report


def compare_sales_windows(
    dataset: CommerceDataset,
    previous: TimeWindow,
    current: TimeWindow,
    *,
    item_level: ItemLevel = ItemLevel.SKU,
) -> tuple[TrendComparison, ...]:
    if current.end - current.start != previous.end - previous.start:
        raise ValueError("trend comparison windows must have equal duration")
    previous_report = compute_sales_report(dataset, previous, item_level=item_level)
    current_report = compute_sales_report(dataset, current, item_level=item_level)
    previous_by_id = {metric.item_id: metric for metric in previous_report.metrics}
    current_by_id = {metric.item_id: metric for metric in current_report.metrics}
    item_ids = sorted(set(previous_by_id) | set(current_by_id))
    return tuple(
        TrendComparison(
            item_id=item_id,
            current=current_by_id.get(item_id),
            previous=previous_by_id.get(item_id),
            units_growth_rate=_growth_rate(
                previous_by_id.get(item_id), current_by_id.get(item_id), "units_sold"
            ),
            gross_amount_growth_rate=_growth_rate(
                previous_by_id.get(item_id), current_by_id.get(item_id), "item_gross_amount"
            ),
            order_growth_rate=_growth_rate(
                previous_by_id.get(item_id), current_by_id.get(item_id), "order_count"
            ),
        )
        for item_id in item_ids
    )


def _growth_rate(
    previous: ItemSalesMetric | None,
    current: ItemSalesMetric | None,
    field: str,
) -> Decimal | None:
    if previous is None or current is None:
        return None
    previous_value = Decimal(str(getattr(previous, field)))
    if previous_value == 0:
        return None
    current_value = Decimal(str(getattr(current, field)))
    return (current_value - previous_value) / previous_value
