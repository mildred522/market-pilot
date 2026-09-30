from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "TimeWindow":
        if self.end <= self.start:
            raise ValueError("time window end must be after start")
        return self


class ItemLevel(StrEnum):
    SKU = "sku"
    PRODUCT = "product"


class ItemSalesMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_level: ItemLevel
    item_id: str
    product_id: str
    category_name: str | None = None
    units_sold: Decimal
    order_count: int = Field(ge=0)
    item_gross_amount: Decimal
    item_discount_amount: Decimal | None = None
    item_refund_amount: Decimal | None = None
    currency: str | None = None


class SalesReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: TimeWindow
    item_level: ItemLevel
    metrics: tuple[ItemSalesMetric, ...]
    included_order_count: int = Field(ge=0)
    excluded_order_count: int = Field(ge=0)
    excluded_order_ids: tuple[str, ...] = ()


class OlistProductSalesMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_level: ItemLevel
    item_id: str
    product_id: str
    category_name: str | None = None
    units_sold: Decimal
    order_count: int = Field(ge=0)
    gross_amount: Decimal
    average_unit_price: Decimal | None = None
    seller_count: int = Field(ge=0)
    freight_amount: Decimal | None = None
    currency: str | None = None


class OlistProductSalesReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    window: TimeWindow
    item_level: ItemLevel
    metrics: tuple[OlistProductSalesMetric, ...]
    included_order_count: int = Field(ge=0)
    excluded_order_count: int = Field(ge=0)


class OlistProductTrend(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current: OlistProductSalesMetric
    previous: OlistProductSalesMetric | None = None
    units_growth_rate: Decimal | None = None
    gross_amount_growth_rate: Decimal | None = None
    order_growth_rate: Decimal | None = None


class OlistProductTrendComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_level: ItemLevel
    item_id: str
    product_id: str
    category_name: str | None = None
    current: OlistProductSalesMetric | None = None
    previous: OlistProductSalesMetric | None = None
    units_growth_rate: Decimal | None = None
    gross_amount_growth_rate: Decimal | None = None
    order_growth_rate: Decimal | None = None


class OlistProductTrendReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    current_window: TimeWindow
    baseline_window: TimeWindow
    item_level: ItemLevel
    trends: tuple[OlistProductTrendComparison, ...]
    included_order_count: int = Field(ge=0)
    excluded_order_count: int = Field(ge=0)


class OlistHotProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    item_level: ItemLevel
    item_id: str
    product_id: str
    category_name: str | None = None
    labels: tuple[str, ...]
    confidence: Literal["low", "medium", "high"]
    current: OlistProductSalesMetric
    trend: OlistProductTrend
    evidence: tuple[str, ...] = ()


class OlistHotProductReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    current_window: TimeWindow
    baseline_window: TimeWindow
    item_level: ItemLevel
    candidates: tuple[OlistHotProductCandidate, ...]
    included_order_count: int = Field(ge=0)
    excluded_order_count: int = Field(ge=0)


class TrendComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    current: ItemSalesMetric | None
    previous: ItemSalesMetric | None
    units_growth_rate: Decimal | None = None
    gross_amount_growth_rate: Decimal | None = None
    order_growth_rate: Decimal | None = None


class HotProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    product_id: str
    labels: tuple[str, ...]
    confidence: Literal["low", "medium", "high"]
    current: ItemSalesMetric
    trend: TrendComparison | None = None
    evidence: tuple[str, ...] = ()
