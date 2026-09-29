from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import import_csv_package
from app.commerce.warehouse import CommerceDuckDBArtifactStore, DuckDBStagingTable


def _write_package(root: Path, *, amount: str = "12.50") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "products.csv").write_text(
        "product_id,product_title,category_name\n"
        "p-1,Demo Product,Demo\n",
        encoding="utf-8",
    )
    (root / "skus.csv").write_text(
        "sku_id,product_id,sku_code\n"
        "sku-1,p-1,DEMO-1\n",
        encoding="utf-8",
    )
    (root / "orders.csv").write_text(
        "order_id,ordered_at,order_status,currency\n"
        "o-1,2026-01-01T12:00:00+00:00,fulfilled,BRL\n",
        encoding="utf-8",
    )
    (root / "order_items.csv").write_text(
        "order_id,order_item_id,sku_id,quantity,unit_price,currency\n"
        f"o-1,1,sku-1,2,{amount},BRL\n",
        encoding="utf-8",
    )


def _dataset(root: Path, *, amount: str = "12.50"):
    _write_package(root, amount=amount)
    return import_csv_package(
        root,
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        now=datetime(2026, 1, 8, tzinfo=UTC),
    )


def test_duckdb_artifact_round_trips_canonical_tables(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "input")
    store = CommerceDuckDBArtifactStore(tmp_path / "artifacts")

    artifact = store.write(dataset)
    metadata = store.read_snapshot_metadata(dataset.snapshot.snapshot_id)

    assert artifact.is_file()
    assert metadata == dataset.snapshot
    with duckdb.connect(str(artifact), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM skus").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone() == (1,)
        assert connection.execute(
            "SELECT SUM(quantity * unit_price) FROM order_items"
        ).fetchone()[0] == 25


def test_duckdb_artifact_persists_source_specific_staging_table(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "input")
    store = CommerceDuckDBArtifactStore(tmp_path / "artifacts")
    staging = DuckDBStagingTable(
        table_name="olist_orders_staging",
        source_file="olist_orders_dataset.csv",
        content_hash="raw-hash",
        columns=("order_id", "order_status"),
        rows=(("o-1", "delivered"),),
    )

    artifact = store.write(dataset, staging_tables=(staging,))

    with duckdb.connect(str(artifact), read_only=True) as connection:
        assert connection.execute(
            "SELECT order_id, order_status FROM olist_orders_staging"
        ).fetchone() == ("o-1", "delivered")
        assert connection.execute(
            "SELECT source_file, table_name, row_count FROM source_files"
        ).fetchone() == ("olist_orders_dataset.csv", "olist_orders_staging", 1)


def test_duckdb_artifact_write_is_idempotent(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "input")
    store = CommerceDuckDBArtifactStore(tmp_path / "artifacts")

    first = store.write(dataset)
    second = store.write(dataset)

    assert second == first


def test_duckdb_artifact_rejects_same_id_with_different_content(tmp_path: Path) -> None:
    first = _dataset(tmp_path / "first")
    second = _dataset(tmp_path / "second", amount="99.00").model_copy(
        update={
            "snapshot": _dataset(tmp_path / "second", amount="99.00").snapshot.model_copy(
                update={"snapshot_id": first.snapshot.snapshot_id}
            )
        }
    )
    store = CommerceDuckDBArtifactStore(tmp_path / "artifacts")
    store.write(first)

    with pytest.raises(ValueError, match="different DuckDB artifact"):
        store.write(second)
