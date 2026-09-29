from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.commerce.canonical.models import (
    OrderItemRecord,
    OrderRecord,
    ProductRecord,
    SkuRecord,
)
from app.commerce.contracts import CommerceAnalysisMode, CommerceCapability
from app.commerce.snapshot import CommerceSnapshot


CORE_FILES = ("products.csv", "skus.csv", "orders.csv", "order_items.csv")
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "products.csv": ("product_id", "product_title"),
    "skus.csv": ("sku_id", "product_id"),
    "orders.csv": ("order_id", "ordered_at"),
    "order_items.csv": ("order_id", "order_item_id", "sku_id", "quantity", "unit_price"),
}


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: str = Field(pattern="^(error|warning)$")
    code: str = Field(min_length=1, max_length=80)
    table: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    row_number: int | None = Field(default=None, ge=2)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_counts: dict[str, int] = Field(default_factory=dict)
    issues: tuple[QualityIssue, ...] = ()

    @property
    def blocking(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


class CommerceDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: CommerceSnapshot
    products: tuple[ProductRecord, ...]
    skus: tuple[SkuRecord, ...]
    orders: tuple[OrderRecord, ...]
    order_items: tuple[OrderItemRecord, ...]
    quality: QualityReport


class CommerceImportError(ValueError):
    def __init__(self, report: QualityReport) -> None:
        self.report = report
        super().__init__("commerce CSV package failed quality validation")


def import_csv_package(
    root: Path,
    *,
    mode: CommerceAnalysisMode,
    source_type: str = "merchant_upload",
    timezone: str | None = None,
    now: datetime | None = None,
) -> CommerceDataset:
    """Read a standard four-file package and create one immutable snapshot."""
    root = root.resolve()
    issues: list[QualityIssue] = []
    raw_files: dict[str, bytes] = {}
    rows: dict[str, list[dict[str, str]]] = {}

    for filename in CORE_FILES:
        path = root / filename
        if not path.is_file():
            issues.append(
                QualityIssue(
                    severity="error",
                    code="missing_file",
                    table=filename,
                    message=f"required file is missing: {filename}",
                )
            )
            continue
        try:
            raw = path.read_bytes()
            parsed_rows, headers = _read_csv(raw, filename)
        except (OSError, UnicodeDecodeError, csv.Error) as error:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="invalid_csv",
                    table=filename,
                    message=str(error),
                )
            )
            continue
        missing = sorted(set(REQUIRED_COLUMNS[filename]) - set(headers))
        if missing:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="missing_columns",
                    table=filename,
                    message=f"missing required columns: {', '.join(missing)}",
                )
            )
        if not parsed_rows:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="empty_file",
                    table=filename,
                    message=f"required file has no data rows: {filename}",
                )
            )
        raw_files[filename] = raw
        rows[filename] = parsed_rows

    if any(issue.severity == "error" for issue in issues):
        raise CommerceImportError(
            QualityReport(row_counts={name: len(value) for name, value in rows.items()}, issues=tuple(issues))
        )

    products = _parse_records(rows["products.csv"], "products.csv", ProductRecord, issues)
    skus = _parse_records(rows["skus.csv"], "skus.csv", SkuRecord, issues)
    orders = _parse_orders(rows["orders.csv"], issues)
    order_items = _parse_records(rows["order_items.csv"], "order_items.csv", OrderItemRecord, issues)

    _check_unique(products, "products.csv", "product_id", issues)
    _check_unique(skus, "skus.csv", "sku_id", issues)
    _check_unique(orders, "orders.csv", "order_id", issues)
    _check_unique(
        order_items,
        "order_items.csv",
        "order_id/order_item_id",
        issues,
        key=lambda item: (item.order_id, item.order_item_id),
    )
    _check_foreign_keys(products, skus, orders, order_items, issues)

    quality = QualityReport(
        row_counts={
            "products": len(products),
            "skus": len(skus),
            "orders": len(orders),
            "order_items": len(order_items),
        },
        issues=tuple(issues),
    )
    if quality.blocking:
        raise CommerceImportError(quality)

    content_hash = _content_hash(raw_files)
    snapshot = CommerceSnapshot(
        snapshot_id=f"csv-{content_hash[:16]}",
        mode=mode,
        source_type=source_type,
        schema_version="commerce-csv-v1",
        content_hash=content_hash,
        created_at=now or datetime.now(UTC),
        period_start=min((order.ordered_at for order in orders), default=None),
        period_end=max((order.ordered_at for order in orders), default=None),
        timezone=timezone,
        capabilities=frozenset({CommerceCapability.CATALOG, CommerceCapability.SALES}),
        row_counts=quality.row_counts,
    )
    return CommerceDataset(
        snapshot=snapshot,
        products=tuple(products),
        skus=tuple(skus),
        orders=tuple(orders),
        order_items=tuple(order_items),
        quality=quality,
    )


def _read_csv(raw: bytes, filename: str) -> tuple[list[dict[str, str]], list[str]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    headers = [str(field).strip() for field in (reader.fieldnames or [])]
    if not headers:
        raise csv.Error(f"{filename} has no header")
    if len(headers) != len(set(headers)):
        raise csv.Error(f"{filename} has duplicate columns")
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({key: (value or "").strip() for key, value in row.items() if key is not None})
    return rows, headers


def _parse_records(
    rows: Iterable[dict[str, str]],
    filename: str,
    model: type[BaseModel],
    issues: list[QualityIssue],
) -> list[Any]:
    records: list[Any] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            values = _clean_optional_values(row)
            values.update(source_file=filename, source_row_number=row_number)
            records.append(model.model_validate(values))
        except (ValidationError, ValueError, InvalidOperation, TypeError) as error:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="invalid_record",
                    table=filename,
                    row_number=row_number,
                    message=str(error)[:500],
                )
            )
    return records


def _parse_orders(rows: Iterable[dict[str, str]], issues: list[QualityIssue]) -> list[OrderRecord]:
    records: list[OrderRecord] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            values = _clean_optional_values(row)
            values.update(source_file="orders.csv", source_row_number=row_number)
            values["ordered_at"] = _parse_datetime(values["ordered_at"])
            records.append(OrderRecord.model_validate(values))
        except (KeyError, ValidationError, ValueError, InvalidOperation, TypeError) as error:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="invalid_record",
                    table="orders.csv",
                    row_number=row_number,
                    message=str(error)[:500],
                )
            )
    return records


def _clean_optional_values(row: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = dict(row)
    for key, value in tuple(values.items()):
        if value == "":
            values[key] = None
    for key in ("catalog_price", "cost_amount", "discount_amount", "refund_amount"):
        if values.get(key) is not None:
            values[key] = Decimal(str(values[key]))
    if values.get("quantity") is not None:
        values["quantity"] = Decimal(str(values["quantity"]))
    if values.get("unit_price") is not None:
        values["unit_price"] = Decimal(str(values["unit_price"]))
    if values.get("variant_attributes") is not None:
        values["variant_attributes"] = json.loads(values["variant_attributes"])
    return values


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("ordered_at is required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _check_unique(
    records: Iterable[Any],
    table: str,
    label: str,
    issues: list[QualityIssue],
    *,
    key: Any = None,
) -> None:
    key = key or (lambda record: getattr(record, label))
    seen: set[Any] = set()
    for record in records:
        value = key(record)
        if value in seen:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="duplicate_key",
                    table=table,
                    row_number=record.source_row_number,
                    message=f"duplicate key: {label}={value}",
                )
            )
        seen.add(value)


def _check_foreign_keys(
    products: Iterable[ProductRecord],
    skus: Iterable[SkuRecord],
    orders: Iterable[OrderRecord],
    order_items: Iterable[OrderItemRecord],
    issues: list[QualityIssue],
) -> None:
    product_ids = {record.product_id for record in products}
    sku_ids = {record.sku_id for record in skus}
    order_ids = {record.order_id for record in orders}
    for sku in skus:
        if sku.product_id not in product_ids:
            _orphan_issue("skus.csv", sku.source_row_number, "product_id", sku.product_id, issues)
    for item in order_items:
        if item.order_id not in order_ids:
            _orphan_issue("order_items.csv", item.source_row_number, "order_id", item.order_id, issues)
        if item.sku_id not in sku_ids:
            _orphan_issue("order_items.csv", item.source_row_number, "sku_id", item.sku_id, issues)


def _orphan_issue(table: str, row_number: int | None, field: str, value: str, issues: list[QualityIssue]) -> None:
    issues.append(
        QualityIssue(
            severity="error",
            code="orphan_reference",
            table=table,
            row_number=row_number,
            message=f"{field} does not reference a known record: {value}",
        )
    )


def _content_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for filename in sorted(files):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[filename])
        digest.update(b"\0")
    return digest.hexdigest()
