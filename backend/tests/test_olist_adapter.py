from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import CommerceImportError
from app.commerce.sources.olist import OlistSourceAdapter


def _write_olist(root: Path, *, with_translation: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at\n"
        "o-1,c-1,delivered,2018-01-01 12:00:00,2018-01-01 12:10:00\n",
        encoding="utf-8",
    )
    (root / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        "o-1,1,p-1,s-1,2018-01-03 12:00:00,12.50,3.00\n",
        encoding="utf-8",
    )
    (root / "olist_products_dataset.csv").write_text(
        "product_id,product_category_name,product_name_lenght\n"
        "p-1,beleza,10\n",
        encoding="utf-8",
    )
    if with_translation:
        (root / "product_category_name_translation.csv").write_text(
            "product_category_name,product_category_name_english\n"
            "beleza,beauty\n",
            encoding="utf-8",
        )


def test_olist_adapter_inspects_required_and_optional_files(tmp_path: Path) -> None:
    _write_olist(tmp_path)
    inspection = OlistSourceAdapter().inspect(tmp_path)

    assert inspection["ready"] is True
    assert inspection["row_counts"]["olist_orders_dataset.csv"] == 1
    assert "olist_sellers_dataset.csv" not in inspection["present_files"]
    assert inspection["content_hash"]

    tables = OlistSourceAdapter().staging_tables(tmp_path)
    assert {table.table_name for table in tables} == {
        "olist_orders_staging",
        "olist_order_items_staging",
        "olist_products_staging",
        "olist_product_category_name_translation_staging",
    }
    assert tables[0].rows[0][0] == "o-1"


def test_olist_adapter_projects_sales_without_inventing_revenue_fields(tmp_path: Path) -> None:
    _write_olist(tmp_path)
    adapter = OlistSourceAdapter()
    snapshot_id = adapter.snapshot_id(tmp_path, currency="BRL")

    dataset = adapter.normalize(
        tmp_path,
        snapshot_id=snapshot_id,
        currency="BRL",
        now=datetime(2026, 1, 9, tzinfo=UTC),
    )

    assert dataset.snapshot.snapshot_id == snapshot_id
    assert dataset.snapshot.schema_version == "olist-canonical-v2"
    assert dataset.snapshot.mode is CommerceAnalysisMode.BENCHMARK
    assert dataset.products[0].category_name == "beauty"
    assert dataset.products[0].source_file == "olist_products_dataset.csv"
    assert dataset.skus[0].sku_id == "olist:p-1"
    assert dataset.orders[0].status.value == "fulfilled"
    assert dataset.order_items[0].quantity == 1
    assert dataset.order_items[0].unit_price == 12.50
    assert any(issue.code == "quantity_assumed_one" for issue in dataset.quality.issues)
    assert all(issue.severity != "error" for issue in dataset.quality.issues)


def test_olist_adapter_rejects_missing_required_file(tmp_path: Path) -> None:
    _write_olist(tmp_path)
    (tmp_path / "olist_products_dataset.csv").unlink()

    with pytest.raises(CommerceImportError, match="failed quality validation"):
        OlistSourceAdapter().normalize(
            tmp_path,
            snapshot_id=OlistSourceAdapter().snapshot_id(tmp_path),
        )
