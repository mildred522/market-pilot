from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from app.commerce.metrics.contracts import (
    ItemLevel,
    OlistProductSalesMetric,
    OlistProductSalesReport,
    TimeWindow,
)
from app.commerce.warehouse import CommerceDuckDBArtifactStore, default_commerce_artifact_root


class OlistSalesFactUnavailable(ValueError):
    pass


class OlistSalesFactRepository:
    """Read deterministic product sales facts from an Olist DuckDB artifact."""

    def __init__(self, artifact_root: Path | None = None) -> None:
        self._store = CommerceDuckDBArtifactStore(
            artifact_root or default_commerce_artifact_root()
        )

    def product_sales(
        self,
        snapshot_id: str,
        window: TimeWindow,
        *,
        item_level: ItemLevel = ItemLevel.PRODUCT,
    ) -> OlistProductSalesReport:
        artifact = self._store.path_for(snapshot_id)
        if not artifact.is_file():
            raise OlistSalesFactUnavailable("Olist sales artifact is not available")
        try:
            with duckdb.connect(str(artifact), read_only=True) as connection:
                self._require_tables(connection)
                metrics = self._metrics(connection, snapshot_id, window, item_level)
                included, excluded = self._order_counts(connection, window)
        except duckdb.Error as error:
            raise OlistSalesFactUnavailable("Olist sales artifact cannot be queried") from error
        return OlistProductSalesReport(
            snapshot_id=snapshot_id,
            window=window,
            item_level=item_level,
            metrics=metrics,
            included_order_count=included,
            excluded_order_count=excluded,
        )

    @staticmethod
    def _require_tables(connection: duckdb.DuckDBPyConnection) -> None:
        available = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        required = {
            "olist_orders_staging",
            "olist_order_items_staging",
            "products",
            "order_items",
        }
        if not required.issubset(available):
            raise OlistSalesFactUnavailable("Olist sales fact tables are missing")

    @staticmethod
    def _metrics(
        connection: duckdb.DuckDBPyConnection,
        snapshot_id: str,
        window: TimeWindow,
        item_level: ItemLevel,
    ) -> tuple[OlistProductSalesMetric, ...]:
        item_expression = (
            "'olist:' || fact.product_id"
            if item_level is ItemLevel.SKU
            else "fact.product_id"
        )
        rows = connection.execute(
            f"""
            WITH sales_fact AS (
                SELECT
                    raw.order_id,
                    raw.product_id,
                    NULLIF(raw.seller_id, '') AS seller_id,
                    TRY_CAST(orders.order_purchase_timestamp AS TIMESTAMP) AS ordered_at,
                    CASE LOWER(orders.order_status)
                        WHEN 'delivered' THEN 'fulfilled'
                        WHEN 'shipped' THEN 'fulfilled'
                        WHEN 'approved' THEN 'paid'
                        WHEN 'invoiced' THEN 'paid'
                        WHEN 'created' THEN 'pending'
                        WHEN 'processing' THEN 'pending'
                        WHEN 'canceled' THEN 'cancelled'
                        WHEN 'unavailable' THEN 'cancelled'
                        ELSE 'unknown'
                    END AS canonical_status,
                    canonical.quantity,
                    canonical.unit_price,
                    canonical.currency,
                    TRY_CAST(NULLIF(raw.freight_value, '') AS DECIMAL(18, 4)) AS freight_value
                FROM olist_order_items_staging AS raw
                INNER JOIN olist_orders_staging AS orders
                    ON orders.order_id = raw.order_id
                INNER JOIN order_items AS canonical
                    ON canonical.order_id = raw.order_id
                   AND canonical.order_item_id = raw.order_item_id
                WHERE TRY_CAST(orders.order_purchase_timestamp AS TIMESTAMP) IS NOT NULL
            )
            SELECT
                {item_expression} AS item_id,
                fact.product_id,
                products.category_name,
                SUM(fact.quantity) AS units_sold,
                COUNT(DISTINCT fact.order_id) AS order_count,
                SUM(fact.quantity * fact.unit_price) AS gross_amount,
                SUM(fact.quantity * fact.unit_price) / NULLIF(SUM(fact.quantity), 0)
                    AS average_unit_price,
                COUNT(DISTINCT fact.seller_id) AS seller_count,
                SUM(fact.freight_value) AS freight_amount,
                CASE
                    WHEN COUNT(DISTINCT NULLIF(fact.currency, '')) = 1
                    THEN MIN(NULLIF(fact.currency, ''))
                    ELSE NULL
                END AS currency
            FROM sales_fact AS fact
            LEFT JOIN products
                ON products.product_id = fact.product_id
            WHERE fact.canonical_status IN ('paid', 'fulfilled')
              AND fact.ordered_at >= ?
              AND fact.ordered_at < ?
            GROUP BY {item_expression}, fact.product_id, products.category_name
            ORDER BY gross_amount DESC, item_id ASC
            """,
            [_naive_utc(window.start), _naive_utc(window.end)],
        ).fetchall()
        return tuple(
            OlistProductSalesMetric(
                item_level=item_level,
                item_id=row[0],
                product_id=row[1],
                category_name=row[2],
                units_sold=row[3],
                order_count=row[4],
                gross_amount=row[5],
                average_unit_price=row[6],
                seller_count=row[7],
                freight_amount=row[8],
                currency=row[9],
            )
            for row in rows
        )

    @staticmethod
    def _order_counts(
        connection: duckdb.DuckDBPyConnection,
        window: TimeWindow,
    ) -> tuple[int, int]:
        included, excluded = connection.execute(
            """
            SELECT
                COUNT(DISTINCT CASE
                    WHEN CASE LOWER(order_status)
                        WHEN 'delivered' THEN 'fulfilled'
                        WHEN 'shipped' THEN 'fulfilled'
                        WHEN 'approved' THEN 'paid'
                        WHEN 'invoiced' THEN 'paid'
                        WHEN 'created' THEN 'pending'
                        WHEN 'processing' THEN 'pending'
                        WHEN 'canceled' THEN 'cancelled'
                        WHEN 'unavailable' THEN 'cancelled'
                        ELSE 'unknown'
                    END IN ('paid', 'fulfilled') THEN order_id
                END) AS included_order_count,
                COUNT(DISTINCT CASE
                    WHEN CASE LOWER(order_status)
                        WHEN 'delivered' THEN 'fulfilled'
                        WHEN 'shipped' THEN 'fulfilled'
                        WHEN 'approved' THEN 'paid'
                        WHEN 'invoiced' THEN 'paid'
                        WHEN 'created' THEN 'pending'
                        WHEN 'processing' THEN 'pending'
                        WHEN 'canceled' THEN 'cancelled'
                        WHEN 'unavailable' THEN 'cancelled'
                        ELSE 'unknown'
                    END NOT IN ('paid', 'fulfilled') THEN order_id
                END) AS excluded_order_count
            FROM olist_orders_staging
            WHERE TRY_CAST(order_purchase_timestamp AS TIMESTAMP) >= ?
              AND TRY_CAST(order_purchase_timestamp AS TIMESTAMP) < ?
            """,
            [_naive_utc(window.start), _naive_utc(window.end)],
        ).fetchone()
        return int(included or 0), int(excluded or 0)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
