from __future__ import annotations

from decimal import Decimal

from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics.contracts import (
    CategorySalesMetric,
    CategorySalesReport,
    CategoryTrendComparison,
    ItemLevel,
    ItemSalesMetric,
    TimeWindow,
    TrendComparison,
)
from app.commerce.metrics.sales import compute_sales_report


def compare_category_sales_reports(
    previous: CategorySalesReport,
    current: CategorySalesReport,
) -> tuple[CategoryTrendComparison, ...]:
    if previous.snapshot_id != current.snapshot_id:
        raise ValueError("category comparison requires the same snapshot")
    if current.window.end - current.window.start != previous.window.end - previous.window.start:
        raise ValueError("category comparison windows must have equal duration")
    if previous.window.end > current.window.start:
        raise ValueError("category comparison windows must not overlap")
    previous_by_name = {category.category_name: category for category in previous.categories}
    current_by_name = {category.category_name: category for category in current.categories}
    names = set(previous_by_name) | set(current_by_name)
    return tuple(
        CategoryTrendComparison(
            category_name=name,
            previous=previous_by_name.get(name),
            current=current_by_name.get(name),
            units_growth_rate=_category_growth(
                previous_by_name.get(name), current_by_name.get(name), "units_sold"
            ),
            gross_amount_growth_rate=_category_growth(
                previous_by_name.get(name), current_by_name.get(name), "gross_amount"
            ),
            order_growth_rate=_category_growth(
                previous_by_name.get(name), current_by_name.get(name), "order_count"
            ),
        )
        for name in sorted(names, key=lambda name: (name is None, name or ""))
    )


def _category_growth(
    previous: CategorySalesMetric | None,
    current: CategorySalesMetric | None,
    field: str,
) -> Decimal | None:
    if previous is None or current is None:
        return None
    if field == "gross_amount" and (
        not previous.currency or not current.currency or previous.currency != current.currency
    ):
        return None
    previous_value = Decimal(str(getattr(previous, field)))
    if previous_value == 0:
        return None
    return (Decimal(str(getattr(current, field))) - previous_value) / previous_value


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
