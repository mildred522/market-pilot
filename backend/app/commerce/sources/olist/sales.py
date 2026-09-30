from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from app.commerce.metrics.contracts import (
    ItemLevel,
    OlistHotProductCandidate,
    OlistHotProductReport,
    OlistProductSalesMetric,
    OlistProductSalesReport,
    OlistProductTrend,
    OlistProductTrendComparison,
    OlistProductTrendReport,
    OlistSelectionRecommendation,
    OlistSelectionRecommendationReport,
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

    def hot_products(
        self,
        snapshot_id: str,
        current_window: TimeWindow,
        baseline_window: TimeWindow,
        *,
        item_level: ItemLevel = ItemLevel.PRODUCT,
        limit: int = 20,
    ) -> OlistHotProductReport:
        if limit < 1:
            raise ValueError("hot product limit must be positive")
        artifact = self._store.path_for(snapshot_id)
        if not artifact.is_file():
            raise OlistSalesFactUnavailable("Olist sales artifact is not available")
        try:
            with duckdb.connect(str(artifact), read_only=True) as connection:
                self._require_tables(connection)
                current = self._metrics(connection, snapshot_id, current_window, item_level)
                previous = self._metrics(connection, snapshot_id, baseline_window, item_level)
                included, excluded = self._order_counts(connection, current_window)
        except duckdb.Error as error:
            raise OlistSalesFactUnavailable("Olist sales artifact cannot be queried") from error

        previous_by_item = {metric.item_id: metric for metric in previous}
        candidates = self._hot_candidates(current, previous_by_item, limit)
        return OlistHotProductReport(
            snapshot_id=snapshot_id,
            current_window=current_window,
            baseline_window=baseline_window,
            item_level=item_level,
            candidates=candidates,
            included_order_count=included,
            excluded_order_count=excluded,
        )

    def product_trends(
        self,
        snapshot_id: str,
        current_window: TimeWindow,
        baseline_window: TimeWindow,
        *,
        item_level: ItemLevel = ItemLevel.PRODUCT,
    ) -> OlistProductTrendReport:
        if current_window.end - current_window.start != baseline_window.end - baseline_window.start:
            raise ValueError("trend comparison windows must have equal duration")
        artifact = self._store.path_for(snapshot_id)
        if not artifact.is_file():
            raise OlistSalesFactUnavailable("Olist sales artifact is not available")
        try:
            with duckdb.connect(str(artifact), read_only=True) as connection:
                self._require_tables(connection)
                current = self._metrics(connection, snapshot_id, current_window, item_level)
                previous = self._metrics(connection, snapshot_id, baseline_window, item_level)
                included, excluded = self._order_counts(connection, current_window)
        except duckdb.Error as error:
            raise OlistSalesFactUnavailable("Olist sales artifact cannot be queried") from error

        current_by_id = {metric.item_id: metric for metric in current}
        previous_by_id = {metric.item_id: metric for metric in previous}
        trends = tuple(
            self._trend_comparison(
                current_by_id.get(item_id),
                previous_by_id.get(item_id),
            )
            for item_id in sorted(set(current_by_id) | set(previous_by_id))
        )
        return OlistProductTrendReport(
            snapshot_id=snapshot_id,
            current_window=current_window,
            baseline_window=baseline_window,
            item_level=item_level,
            trends=trends,
            included_order_count=included,
            excluded_order_count=excluded,
        )

    def selection_recommendations(
        self,
        snapshot_id: str,
        current_window: TimeWindow,
        baseline_window: TimeWindow,
        *,
        item_level: ItemLevel = ItemLevel.PRODUCT,
        limit: int = 10,
    ) -> OlistSelectionRecommendationReport:
        if limit < 1:
            raise ValueError("selection recommendation limit must be positive")
        trend_report = self.product_trends(
            snapshot_id,
            current_window,
            baseline_window,
            item_level=item_level,
        )
        current_rank = {
            metric.item_id: index
            for index, metric in enumerate(
                sorted(
                    (trend.current for trend in trend_report.trends if trend.current),
                    key=lambda metric: (-metric.gross_amount, metric.item_id),
                ),
                1,
            )
        }
        recommendations = [
            recommendation
            for trend in trend_report.trends
            if (
                recommendation := self._recommendation_for_trend(
                    trend,
                    current_rank.get(trend.item_id),
                )
            )
            is not None
        ]
        recommendations.sort(
            key=lambda recommendation: (
                {"high": 0, "medium": 1, "low": 2}[recommendation.priority],
                current_rank.get(recommendation.item_id, 10**9),
                recommendation.item_id,
            )
        )
        ranked = tuple(
            recommendation.model_copy(update={"rank": index})
            for index, recommendation in enumerate(recommendations[:limit], 1)
        )
        return OlistSelectionRecommendationReport(
            snapshot_id=snapshot_id,
            current_window=current_window,
            baseline_window=baseline_window,
            item_level=item_level,
            recommendations=ranked,
            included_order_count=trend_report.included_order_count,
            excluded_order_count=trend_report.excluded_order_count,
        )

    @staticmethod
    def _recommendation_for_trend(
        trend: OlistProductTrendComparison,
        current_rank: int | None,
    ) -> OlistSelectionRecommendation | None:
        current = trend.current
        previous = trend.previous
        if current is None and previous is not None:
            return OlistSelectionRecommendation(
                rank=1,
                recommendation_type="review_decline",
                priority="high",
                item_level=trend.item_level,
                item_id=trend.item_id,
                product_id=trend.product_id,
                category_name=trend.category_name,
                title=f"复核商品 {trend.item_id} 是否继续经营",
                action="检查库存、价格和商品状态，再决定补货、优化或暂缓投入。",
                rationale="商品只在基线窗口成交，当前窗口没有可确认的成交记录。",
                evidence=("当前窗口无成交记录", "基线窗口存在成交记录"),
                risk_flags=("无法仅凭销售事实判断下架原因",),
                current=None,
                trend=trend,
            )
        if current is None:
            return None
        if previous is None:
            return OlistSelectionRecommendation(
                rank=1,
                recommendation_type="validate_new_product",
                priority="medium",
                item_level=trend.item_level,
                item_id=trend.item_id,
                product_id=trend.product_id,
                category_name=trend.category_name,
                title=f"小规模验证商品 {trend.item_id}",
                action="先做受控的小规模测试，补充连续窗口数据后再扩大投入。",
                rationale="商品在当前窗口出现成交，但没有可比的基线表现。",
                evidence=("当前窗口有成交记录", "基线窗口无成交记录"),
                risk_flags=("缺少历史基线", "销售额不是利润"),
                current=current,
                trend=trend,
            )
        if _at_least_growth(trend.gross_amount_growth_rate, Decimal("0.20")):
            priority = "high" if current.order_count >= 3 else "medium"
            return OlistSelectionRecommendation(
                rank=1,
                recommendation_type="scale_test",
                priority=priority,
                item_level=trend.item_level,
                item_id=trend.item_id,
                product_id=trend.product_id,
                category_name=trend.category_name,
                title=f"扩大验证商品 {trend.item_id}",
                action="增加有限的供给或曝光测试，并观察下一等长窗口是否延续增长。",
                rationale="商品销售额相对基线窗口增长至少 20%，但仍需控制扩张风险。",
                evidence=(f"销售额增长率 {trend.gross_amount_growth_rate:+.1%}",),
                risk_flags=("销售额不是利润", "缺少成本、库存和流量证据"),
                current=current,
                trend=trend,
            )
        if _at_most_growth(trend.gross_amount_growth_rate, Decimal("-0.20")):
            return OlistSelectionRecommendation(
                rank=1,
                recommendation_type="review_decline",
                priority="high",
                item_level=trend.item_level,
                item_id=trend.item_id,
                product_id=trend.product_id,
                category_name=trend.category_name,
                title=f"复核商品 {trend.item_id} 的下降原因",
                action="对比价格、详情页、库存和流量变化，再决定优化或减少投入。",
                rationale="商品销售额相对基线窗口下降至少 20%，但销售事实本身不能解释原因。",
                evidence=(f"销售额增长率 {trend.gross_amount_growth_rate:+.1%}",),
                risk_flags=("无法仅凭销售事实判断下降原因",),
                current=current,
                trend=trend,
            )
        if current_rank is not None and current_rank <= 3 and current.order_count >= 3:
            return OlistSelectionRecommendation(
                rank=1,
                recommendation_type="protect_winner",
                priority="medium",
                item_level=trend.item_level,
                item_id=trend.item_id,
                product_id=trend.product_id,
                category_name=trend.category_name,
                title=f"保护商品 {trend.item_id} 的稳定销售",
                action="优先检查供给、价格和关联销售承接，避免稳定商品断供。",
                rationale="商品当前销售额排名靠前且有多笔订单，但没有足够增长证据支持激进扩张。",
                evidence=(f"当前销售额排名第 {current_rank}", f"当前订单数 {current.order_count}"),
                risk_flags=("缺少利润和库存证据",),
                current=current,
                trend=trend,
            )
        return None

    @staticmethod
    def _trend_comparison(
        current: OlistProductSalesMetric | None,
        previous: OlistProductSalesMetric | None,
    ) -> OlistProductTrendComparison:
        metric = current or previous
        assert metric is not None
        return OlistProductTrendComparison(
            item_level=metric.item_level,
            item_id=metric.item_id,
            product_id=metric.product_id,
            category_name=metric.category_name,
            current=current,
            previous=previous,
            units_growth_rate=_growth_rate(
                current.units_sold if current else None,
                previous.units_sold if previous else None,
            ),
            gross_amount_growth_rate=_growth_rate(
                current.gross_amount if current else None,
                previous.gross_amount if previous else None,
            ),
            order_growth_rate=_growth_rate(
                Decimal(current.order_count) if current else None,
                Decimal(previous.order_count) if previous else None,
            ),
        )

    @staticmethod
    def _hot_candidates(
        current: tuple[OlistProductSalesMetric, ...],
        previous_by_item: dict[str, OlistProductSalesMetric],
        limit: int,
    ) -> tuple[OlistHotProductCandidate, ...]:
        if not current:
            return ()
        ranked_by_units = sorted(
            current,
            key=lambda metric: (-metric.units_sold, metric.item_id),
        )
        ranked_by_gross = sorted(
            current,
            key=lambda metric: (-metric.gross_amount, metric.item_id),
        )
        leader_count = max(1, (len(current) + 3) // 4)
        unit_leaders = {metric.item_id for metric in ranked_by_units[:leader_count]}
        gross_leaders = {metric.item_id for metric in ranked_by_gross[:leader_count]}
        candidates: list[OlistHotProductCandidate] = []
        for metric in current:
            previous = previous_by_item.get(metric.item_id)
            trend = OlistProductTrend(
                current=metric,
                previous=previous,
                units_growth_rate=_growth_rate(
                    metric.units_sold,
                    previous.units_sold if previous else None,
                ),
                gross_amount_growth_rate=_growth_rate(
                    metric.gross_amount,
                    previous.gross_amount if previous else None,
                ),
                order_growth_rate=_growth_rate(
                    Decimal(metric.order_count),
                    Decimal(previous.order_count) if previous else None,
                ),
            )
            labels: list[str] = []
            evidence: list[str] = []
            if metric.item_id in unit_leaders:
                labels.append("volume_leader")
                evidence.append("当前窗口销量位于商品前 25%")
            if metric.item_id in gross_leaders:
                labels.append("revenue_leader")
                evidence.append("当前窗口销售额位于商品前 25%")
            if _is_momentum(trend):
                labels.append("momentum")
                evidence.append("相对等长基线窗口增长至少 20%")
            if metric.seller_count >= 2:
                labels.append("multi_seller")
                evidence.append("当前窗口有至少 2 个卖家销售")
            if not labels:
                continue
            confidence = "high" if len(labels) >= 3 else "medium" if len(labels) == 2 else "low"
            candidates.append(
                OlistHotProductCandidate(
                    rank=1,
                    item_level=metric.item_level,
                    item_id=metric.item_id,
                    product_id=metric.product_id,
                    category_name=metric.category_name,
                    labels=tuple(labels),
                    confidence=confidence,
                    current=metric,
                    trend=trend,
                    evidence=tuple(evidence),
                )
            )
        candidates.sort(
            key=lambda candidate: (
                {"high": 0, "medium": 1, "low": 2}[candidate.confidence],
                -len(candidate.labels),
                -candidate.current.gross_amount,
                candidate.item_id,
            )
        )
        return tuple(candidate.model_copy(update={"rank": index}) for index, candidate in enumerate(candidates[:limit], 1))

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


def _growth_rate(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous


def _is_momentum(trend: OlistProductTrend) -> bool:
    return any(
        growth is not None and growth >= Decimal("0.20")
        for growth in (
            trend.units_growth_rate,
            trend.gross_amount_growth_rate,
            trend.order_growth_rate,
        )
    )


def _at_least_growth(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _at_most_growth(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value <= threshold
