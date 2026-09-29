from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    UNKNOWN = "unknown"


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_file: str | None = Field(default=None, max_length=500)
    source_row_number: int | None = Field(default=None, ge=1)
    source_record_id: str | None = Field(default=None, max_length=200)


class ProductRecord(SourceRecord):
    product_id: str = Field(min_length=1, max_length=200)
    product_title: str = Field(min_length=1, max_length=500)
    category_id: str | None = Field(default=None, max_length=200)
    category_name: str | None = Field(default=None, max_length=200)
    brand: str | None = Field(default=None, max_length=200)
    status: ProductStatus = ProductStatus.UNKNOWN


class SkuRecord(SourceRecord):
    sku_id: str = Field(min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=200)
    sku_code: str | None = Field(default=None, max_length=200)
    variant_attributes: dict[str, Any] = Field(default_factory=dict)
    catalog_price: Decimal | None = Field(default=None, ge=0)
    cost_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class OrderRecord(SourceRecord):
    order_id: str = Field(min_length=1, max_length=200)
    ordered_at: datetime
    status: OrderStatus = OrderStatus.UNKNOWN
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    customer_key: str | None = Field(default=None, max_length=200)
    channel: str | None = Field(default=None, max_length=120)


class OrderItemRecord(SourceRecord):
    order_id: str = Field(min_length=1, max_length=200)
    order_item_id: str = Field(min_length=1, max_length=200)
    sku_id: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    discount_amount: Decimal | None = Field(default=None, ge=0)
    refund_amount: Decimal | None = Field(default=None, ge=0)
