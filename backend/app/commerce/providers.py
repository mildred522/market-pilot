from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.commerce.ingestion import CommerceDataset
from app.commerce.metrics import (
    CategorySalesReport,
    ItemLevel,
    OlistHotProductReport,
    OlistProductSalesReport,
    OlistProductTrendReport,
    OlistSelectionRecommendationReport,
    TimeWindow,
    compare_sales_windows,
    compute_category_sales_report,
    compute_sales_report,
    discover_hot_products,
)
from app.commerce.sources.olist import OlistSalesFactRepository


class CommerceFactProvider(Protocol):
    def category_sales(self, window: TimeWindow) -> CategorySalesReport: ...

    def sales(
        self,
        window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> object: ...

    def trends(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> object: ...

    def hot_products(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> object: ...

    def selection_recommendations(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> OlistSelectionRecommendationReport | None: ...


@dataclass(frozen=True)
class DatasetCommerceFactProvider:
    dataset: CommerceDataset

    def category_sales(self, window: TimeWindow) -> CategorySalesReport:
        return compute_category_sales_report(self.dataset, window)

    def sales(self, window: TimeWindow, *, item_level: ItemLevel) -> object:
        return compute_sales_report(self.dataset, window, item_level=item_level)

    def trends(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> object:
        return compare_sales_windows(
            self.dataset,
            previous_window,
            current_window,
            item_level=item_level,
        )

    def hot_products(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> object:
        return discover_hot_products(
            self.dataset,
            previous_window,
            current_window,
            item_level=item_level,
        )

    def selection_recommendations(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> None:
        return None


@dataclass(frozen=True)
class OlistDuckDBFactProvider:
    snapshot_id: str
    repository: OlistSalesFactRepository

    def category_sales(self, window: TimeWindow) -> CategorySalesReport:
        report = self.repository.category_sales(self.snapshot_id, window)
        return CategorySalesReport(
            snapshot_id=report.snapshot_id,
            window=report.window,
            categories=tuple(
                {
                    "category_name": category.category_name,
                    "product_count": category.product_count,
                    "units_sold": category.units_sold,
                    "order_count": category.order_count,
                    "gross_amount": category.gross_amount,
                    "currency": category.currency,
                }
                for category in report.categories
            ),
            included_order_count=report.included_order_count,
            excluded_order_count=report.excluded_order_count,
        )

    def sales(self, window: TimeWindow, *, item_level: ItemLevel) -> OlistProductSalesReport:
        return self.repository.product_sales(
            self.snapshot_id,
            window,
            item_level=item_level,
        )

    def trends(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> OlistProductTrendReport:
        return self.repository.product_trends(
            self.snapshot_id,
            current_window,
            previous_window,
            item_level=item_level,
        )

    def hot_products(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> OlistHotProductReport:
        return self.repository.hot_products(
            self.snapshot_id,
            current_window,
            previous_window,
            item_level=item_level,
        )

    def selection_recommendations(
        self,
        previous_window: TimeWindow,
        current_window: TimeWindow,
        *,
        item_level: ItemLevel,
    ) -> OlistSelectionRecommendationReport:
        return self.repository.selection_recommendations(
            self.snapshot_id,
            current_window,
            previous_window,
            item_level=item_level,
        )
