from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.commerce.contracts import CommerceAnalysisMode, CommerceCapability
from app.commerce.ingestion import (
    CommerceDataset,
    CommerceImportError,
    QualityIssue,
    QualityReport,
    import_csv_package,
)
from app.commerce.sources.base import CommerceSourceAdapter
from app.commerce.warehouse import DuckDBStagingTable


ADAPTER_VERSION = "olist-canonical-v2"
REQUIRED_FILES = (
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_products_dataset.csv",
)
OPTIONAL_FILES = (
    "olist_sellers_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_order_payments_dataset.csv",
    "product_category_name_translation.csv",
)
SUPPORTED_FILES = REQUIRED_FILES + OPTIONAL_FILES
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "olist_orders_dataset.csv": (
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
    ),
    "olist_order_items_dataset.csv": (
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "price",
        "freight_value",
    ),
    "olist_products_dataset.csv": ("product_id",),
    "product_category_name_translation.csv": (
        "product_category_name",
        "product_category_name_english",
    ),
}


class OlistSourceAdapter(CommerceSourceAdapter):
    """Project Olist order, item, and product files into canonical sales data."""

    source_type = "public_dataset"

    @property
    def capabilities(self) -> frozenset[CommerceCapability]:
        return frozenset({CommerceCapability.CATALOG, CommerceCapability.SALES})

    def inspect(self, source: Any) -> dict[str, Any]:
        root = self._root(source)
        issues: list[QualityIssue] = []
        row_counts: dict[str, int] = {}
        present_files: list[str] = []
        for filename in SUPPORTED_FILES:
            path = root / filename
            if not path.is_file():
                if filename in REQUIRED_FILES:
                    issues.append(
                        QualityIssue(
                            severity="error",
                            code="missing_file",
                            table=filename,
                            message=f"required Olist file is missing: {filename}",
                        )
                    )
                continue
            present_files.append(filename)
            try:
                rows, headers = self._read_csv(path, filename)
            except (OSError, UnicodeDecodeError, csv.Error) as error:
                issues.append(
                    QualityIssue(
                        severity="error",
                        code="invalid_csv",
                        table=filename,
                        message=str(error)[:500],
                    )
                )
                continue
            row_counts[filename] = len(rows)
            missing = sorted(set(REQUIRED_COLUMNS.get(filename, ())) - set(headers))
            if missing:
                issues.append(
                    QualityIssue(
                        severity="error",
                        code="missing_columns",
                        table=filename,
                        message=f"missing required columns: {', '.join(missing)}",
                    )
                )
            if filename in REQUIRED_FILES and not rows:
                issues.append(
                    QualityIssue(
                        severity="error",
                        code="empty_file",
                        table=filename,
                        message=f"required Olist file has no data rows: {filename}",
                    )
                )
        return {
            "adapter_version": ADAPTER_VERSION,
            "source_type": self.source_type,
            "required_files": list(REQUIRED_FILES),
            "optional_files": list(OPTIONAL_FILES),
            "present_files": present_files,
            "row_counts": row_counts,
            "content_hash": self.content_hash(root),
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "ready": not any(issue.severity == "error" for issue in issues),
        }

    def content_hash(self, source: Path) -> str:
        root = self._root(source)
        digest = hashlib.sha256()
        digest.update(ADAPTER_VERSION.encode("utf-8"))
        digest.update(b"\0")
        for filename in SUPPORTED_FILES:
            path = root / filename
            if not path.is_file():
                continue
            digest.update(filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def snapshot_id(
        self,
        source: Path,
        *,
        currency: str | None = None,
        timezone: str | None = None,
    ) -> str:
        return f"olist-{self.snapshot_content_hash(source, currency=currency, timezone=timezone)[:16]}"

    def snapshot_content_hash(
        self,
        source: Path,
        *,
        currency: str | None = None,
        timezone: str | None = None,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(self.content_hash(source).encode("utf-8"))
        digest.update(b"\0")
        digest.update((currency or "").upper().encode("utf-8"))
        digest.update(b"\0")
        digest.update((timezone or "").encode("utf-8"))
        return digest.hexdigest()

    def normalize(
        self,
        source: Any,
        *,
        snapshot_id: str,
        currency: str | None = None,
        timezone: str | None = None,
        now: datetime | None = None,
    ) -> CommerceDataset:
        root = self._root(source)
        inspection = self.inspect(root)
        inspection_issues = tuple(
            QualityIssue.model_validate(issue) for issue in inspection["issues"]
        )
        if any(issue.severity == "error" for issue in inspection_issues):
            raise CommerceImportError(
                QualityReport(row_counts=inspection["row_counts"], issues=inspection_issues)
            )

        normalized_currency = currency.upper() if currency else None
        expected_snapshot_id = self.snapshot_id(
            root, currency=normalized_currency, timezone=timezone
        )
        if snapshot_id != expected_snapshot_id:
            raise ValueError("snapshot id does not match the Olist source content")

        raw = {
            filename: self._read_csv(root / filename, filename)[0]
            for filename in REQUIRED_FILES
        }
        translation = self._category_translation(root)
        product_rows, product_sources, title_fallbacks = self._products(
            raw["olist_products_dataset.csv"], translation
        )
        sku_rows, sku_sources = self._skus(raw["olist_order_items_dataset.csv"], normalized_currency)
        order_rows, order_sources = self._orders(
            raw["olist_orders_dataset.csv"], normalized_currency
        )
        order_item_rows, order_item_sources = self._order_items(
            raw["olist_order_items_dataset.csv"], normalized_currency
        )

        with TemporaryDirectory(prefix="market-pilot-olist-") as temporary:
            canonical_root = Path(temporary)
            self._write_csv(canonical_root / "products.csv", product_rows)
            self._write_csv(canonical_root / "skus.csv", sku_rows)
            self._write_csv(canonical_root / "orders.csv", order_rows)
            self._write_csv(canonical_root / "order_items.csv", order_item_rows)
            dataset = import_csv_package(
                canonical_root,
                mode=CommerceAnalysisMode.BENCHMARK,
                source_type=self.source_type,
                timezone=timezone,
                now=now or datetime.now(UTC),
            )

        dataset = dataset.model_copy(
            update={
                "snapshot": dataset.snapshot.model_copy(
                    update={
                        "snapshot_id": snapshot_id,
                        "source_type": self.source_type,
                        "schema_version": ADAPTER_VERSION,
                        "content_hash": self.snapshot_content_hash(
                            root, currency=normalized_currency, timezone=timezone
                        ),
                        "capabilities": self.capabilities,
                    }
                ),
                "products": tuple(
                    record.model_copy(update=product_sources[index])
                    for index, record in enumerate(dataset.products)
                ),
                "skus": tuple(
                    record.model_copy(update=sku_sources[index])
                    for index, record in enumerate(dataset.skus)
                ),
                "orders": tuple(
                    record.model_copy(update=order_sources[index])
                    for index, record in enumerate(dataset.orders)
                ),
                "order_items": tuple(
                    record.model_copy(update=order_item_sources[index])
                    for index, record in enumerate(dataset.order_items)
                ),
                "quality": dataset.quality.model_copy(
                    update={
                        "issues": (
                            *dataset.quality.issues,
                            QualityIssue(
                                severity="warning",
                                code="quantity_assumed_one",
                                table="olist_order_items_dataset.csv",
                                message=(
                                    "Olist does not provide an item quantity column; "
                                    "canonical quantity is set to 1 per source row."
                                ),
                            ),
                            *(
                                [
                                    QualityIssue(
                                        severity="warning",
                                        code="product_title_fallback",
                                        table="olist_products_dataset.csv",
                                        message=(
                                            f"product_title was unavailable for {title_fallbacks} product rows; "
                                            "a stable placeholder was generated."
                                        ),
                                    )
                                ]
                                if title_fallbacks
                                else []
                            ),
                        )
                    }
                ),
            }
        )
        return dataset

    def staging_tables(self, source: Any) -> tuple[DuckDBStagingTable, ...]:
        root = self._root(source)
        tables: list[DuckDBStagingTable] = []
        for filename in SUPPORTED_FILES:
            path = root / filename
            if not path.is_file():
                continue
            rows, headers = self._read_csv(path, filename)
            tables.append(
                DuckDBStagingTable(
                    table_name=_staging_table_name(filename),
                    source_file=filename,
                    content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                    columns=tuple(headers),
                    rows=tuple(
                        tuple(row.get(column) for column in headers)
                        for row in rows
                    ),
                )
            )
        return tuple(tables)

    @staticmethod
    def _root(source: Any) -> Path:
        root = Path(source).resolve()
        if not root.is_dir():
            raise ValueError(f"Olist source directory does not exist: {root}")
        return root

    @staticmethod
    def _read_csv(path: Path, filename: str) -> tuple[list[dict[str, str]], list[str]]:
        raw = path.read_bytes()
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        headers = [str(field).strip() for field in (reader.fieldnames or [])]
        if not headers:
            raise csv.Error(f"{filename} has no header")
        if len(headers) != len(set(headers)):
            raise csv.Error(f"{filename} has duplicate columns")
        rows = [
            {
                key: (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        ]
        return rows, headers

    @staticmethod
    def _category_translation(root: Path) -> dict[str, str]:
        path = root / "product_category_name_translation.csv"
        if not path.is_file():
            return {}
        rows, _ = OlistSourceAdapter._read_csv(path, path.name)
        return {
            row["product_category_name"]: row["product_category_name_english"]
            for row in rows
            if row.get("product_category_name") and row.get("product_category_name_english")
        }

    @staticmethod
    def _products(
        rows: list[dict[str, str]], translation: dict[str, str]
    ) -> tuple[list[dict[str, str]], list[dict[str, object]], int]:
        canonical: list[dict[str, str]] = []
        sources: list[dict[str, object]] = []
        fallbacks = 0
        for row_number, row in enumerate(rows, start=2):
            product_id = row.get("product_id", "")
            category = row.get("product_category_name", "")
            category_name = translation.get(category, category) or None
            if category_name:
                title = category_name
            else:
                title = f"Olist product {product_id}" if product_id else ""
                fallbacks += 1
            canonical.append(
                {
                    "product_id": product_id,
                    "product_title": title,
                    "category_name": category_name or "",
                }
            )
            sources.append(
                {
                    "source_file": "olist_products_dataset.csv",
                    "source_row_number": row_number,
                }
            )
        return canonical, sources, fallbacks

    @staticmethod
    def _skus(
        rows: list[dict[str, str]], currency: str | None
    ) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
        product_ids = dict.fromkeys(row.get("product_id", "") for row in rows)
        canonical = [
            {
                "sku_id": f"olist:{product_id}",
                "product_id": product_id,
                "sku_code": product_id,
                "currency": currency or "",
            }
            for product_id in product_ids
        ]
        sources = [
            {"source_file": "olist_order_items_dataset.csv", "source_row_number": None}
            for _ in canonical
        ]
        return canonical, sources

    @staticmethod
    def _orders(
        rows: list[dict[str, str]], currency: str | None
    ) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
        canonical: list[dict[str, str]] = []
        sources: list[dict[str, object]] = []
        for row_number, row in enumerate(rows, start=2):
            canonical.append(
                {
                    "order_id": row.get("order_id", ""),
                    "ordered_at": row.get("order_purchase_timestamp", ""),
                    "order_status": _map_order_status(row.get("order_status", "")),
                    "currency": currency or "",
                    "customer_key": row.get("customer_id", ""),
                }
            )
            sources.append(
                {
                    "source_file": "olist_orders_dataset.csv",
                    "source_row_number": row_number,
                }
            )
        return canonical, sources

    @staticmethod
    def _order_items(
        rows: list[dict[str, str]], currency: str | None
    ) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
        canonical: list[dict[str, str]] = []
        sources: list[dict[str, object]] = []
        for row_number, row in enumerate(rows, start=2):
            product_id = row.get("product_id", "")
            canonical.append(
                {
                    "order_id": row.get("order_id", ""),
                    "order_item_id": row.get("order_item_id", ""),
                    "sku_id": f"olist:{product_id}",
                    "quantity": "1",
                    "unit_price": row.get("price", ""),
                    "currency": currency or "",
                }
            )
            sources.append(
                {
                    "source_file": "olist_order_items_dataset.csv",
                    "source_row_number": row_number,
                }
            )
        return canonical, sources

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        if not rows:
            raise ValueError(f"cannot write empty canonical table: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0])
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def _map_order_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"delivered", "shipped"}:
        return "fulfilled"
    if normalized in {"approved", "invoiced"}:
        return "paid"
    if normalized in {"created", "processing"}:
        return "pending"
    if normalized in {"canceled", "unavailable"}:
        return "cancelled"
    return "unknown"


def _staging_table_name(filename: str) -> str:
    stem = filename.removesuffix(".csv")
    if stem.startswith("olist_"):
        stem = stem.removeprefix("olist_")
    stem = stem.removesuffix("_dataset")
    return f"olist_{stem}_staging"
