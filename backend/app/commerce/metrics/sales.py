from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from app.commerce.canonical.models import OrderItemRecord, OrderRecord, OrderStatus
from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics.contracts import (
    CategorySalesMetric,
    CategorySalesReport,
    ItemLevel,
    ItemSalesMetric,
    SalesReport,
    TimeWindow,
)


ELIGIBLE_ORDER_STATUSES = frozenset({OrderStatus.PAID, OrderStatus.FULFILLED})


def compute_sales_report(
    dataset: CommerceDataset,
    window: TimeWindow,
    *,
    item_level: ItemLevel = ItemLevel.SKU,
    eligible_statuses: Iterable[OrderStatus] = ELIGIBLE_ORDER_STATUSES,
) -> SalesReport:
    eligible = frozenset(eligible_statuses)
    orders_by_id = {order.order_id: order for order in dataset.orders}
    sku_by_id = {sku.sku_id: sku for sku in dataset.skus}
    product_by_id = {product.product_id: product for product in dataset.products}
    aggregate: dict[str, dict[str, object]] = {}
    included_order_ids: set[str] = set()
    excluded_order_ids: set[str] = set()

    for item in dataset.order_items:
        order = orders_by_id.get(item.order_id)
        if order is None or not _in_window(order.ordered_at, window):
            continue
        if order.status not in eligible:
            excluded_order_ids.add(order.order_id)
            continue
        sku = sku_by_id[item.sku_id]
        product = product_by_id[sku.product_id]
        key = item.sku_id if item_level is ItemLevel.SKU else product.product_id
        bucket = aggregate.setdefault(
            key,
            {
                "product_id": product.product_id,
                "category_name": product.category_name,
                "units_sold": Decimal("0"),
                "order_ids": set(),
                "item_gross_amount": Decimal("0"),
                "discount_values": [],
                "refund_values": [],
                "currencies": set(),
            },
        )
        bucket["units_sold"] += item.quantity  # type: ignore[operator]
        bucket["order_ids"].add(item.order_id)  # type: ignore[union-attr]
        bucket["item_gross_amount"] += item.quantity * item.unit_price  # type: ignore[operator]
        bucket["discount_values"].append(item.discount_amount)  # type: ignore[union-attr]
        bucket["refund_values"].append(item.refund_amount)  # type: ignore[union-attr]
        if item.currency:
            bucket["currencies"].add(item.currency)  # type: ignore[union-attr]
        included_order_ids.add(order.order_id)

    metrics = tuple(
        sorted(
            (
                ItemSalesMetric(
                    item_level=item_level,
                    item_id=item_id,
                    product_id=str(bucket["product_id"]),
                    category_name=bucket["category_name"],  # type: ignore[arg-type]
                    units_sold=bucket["units_sold"],  # type: ignore[arg-type]
                    order_count=len(bucket["order_ids"]),  # type: ignore[arg-type]
                    item_gross_amount=bucket["item_gross_amount"],  # type: ignore[arg-type]
                    item_discount_amount=_known_amount(bucket["discount_values"]),  # type: ignore[arg-type]
                    item_refund_amount=_known_amount(bucket["refund_values"]),  # type: ignore[arg-type]
                    currency=_single_value(bucket["currencies"]),  # type: ignore[arg-type]
                )
                for item_id, bucket in aggregate.items()
            ),
            key=lambda metric: (-metric.item_gross_amount, metric.item_id),
        )
    )
    return SalesReport(
        window=window,
        item_level=item_level,
        metrics=metrics,
        included_order_count=len(included_order_ids),
        excluded_order_count=len(excluded_order_ids),
        excluded_order_ids=tuple(sorted(excluded_order_ids)),
    )


def compute_category_sales_report(
    dataset: CommerceDataset,
    window: TimeWindow,
    *,
    eligible_statuses: Iterable[OrderStatus] = ELIGIBLE_ORDER_STATUSES,
) -> CategorySalesReport:
    eligible = frozenset(eligible_statuses)
    orders_by_id = {order.order_id: order for order in dataset.orders}
    sku_by_id = {sku.sku_id: sku for sku in dataset.skus}
    product_by_id = {product.product_id: product for product in dataset.products}
    aggregate: dict[str | None, dict[str, object]] = {}
    included_order_ids: set[str] = set()
    excluded_order_ids: set[str] = set()

    for item in dataset.order_items:
        order = orders_by_id.get(item.order_id)
        if order is None or not _in_window(order.ordered_at, window):
            continue
        if order.status not in eligible:
            excluded_order_ids.add(order.order_id)
            continue
        product = product_by_id[sku_by_id[item.sku_id].product_id]
        category = product.category_name
        bucket = aggregate.setdefault(
            category,
            {
                "product_ids": set(),
                "order_ids": set(),
                "units_sold": Decimal("0"),
                "gross_amount": Decimal("0"),
                "currencies": set(),
            },
        )
        bucket["product_ids"].add(product.product_id)  # type: ignore[union-attr]
        bucket["order_ids"].add(order.order_id)  # type: ignore[union-attr]
        bucket["units_sold"] += item.quantity  # type: ignore[operator]
        bucket["gross_amount"] += item.quantity * item.unit_price  # type: ignore[operator]
        if item.currency:
            bucket["currencies"].add(item.currency)  # type: ignore[union-attr]
        included_order_ids.add(order.order_id)

    categories = tuple(
        sorted(
            (
                CategorySalesMetric(
                    category_name=category,
                    product_count=len(bucket["product_ids"]),  # type: ignore[arg-type]
                    units_sold=bucket["units_sold"],  # type: ignore[arg-type]
                    order_count=len(bucket["order_ids"]),  # type: ignore[arg-type]
                    gross_amount=bucket["gross_amount"],  # type: ignore[arg-type]
                    currency=_single_value(bucket["currencies"]),  # type: ignore[arg-type]
                )
                for category, bucket in aggregate.items()
            ),
            key=lambda metric: (-metric.gross_amount, metric.category_name or ""),
        )
    )
    return CategorySalesReport(
        snapshot_id=dataset.snapshot.snapshot_id,
        window=window,
        categories=categories,
        included_order_count=len(included_order_ids),
        excluded_order_count=len(excluded_order_ids),
    )


def _in_window(value: datetime, window: TimeWindow) -> bool:
    normalized = _normalize_datetime(value)
    return _normalize_datetime(window.start) <= normalized < _normalize_datetime(window.end)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _known_amount(values: list[Decimal | None]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def _single_value(values: set[str]) -> str | None:
    return next(iter(values)) if len(values) == 1 else None
