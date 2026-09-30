"""Deterministic commerce metrics and candidate discovery."""

from app.commerce.metrics.contracts import (
    HotProductCandidate,
    ItemLevel,
    ItemSalesMetric,
    OlistHotProductCandidate,
    OlistHotProductReport,
    OlistProductSalesMetric,
    OlistProductSalesReport,
    OlistProductTrend,
    SalesReport,
    TimeWindow,
    TrendComparison,
)
from app.commerce.metrics.hot_products import discover_hot_products
from app.commerce.metrics.sales import compute_sales_report
from app.commerce.metrics.trends import compare_sales_windows

__all__ = [
    "HotProductCandidate",
    "ItemLevel",
    "ItemSalesMetric",
    "OlistHotProductCandidate",
    "OlistHotProductReport",
    "OlistProductSalesMetric",
    "OlistProductSalesReport",
    "OlistProductTrend",
    "SalesReport",
    "TimeWindow",
    "TrendComparison",
    "compute_sales_report",
    "compare_sales_windows",
    "discover_hot_products",
]
