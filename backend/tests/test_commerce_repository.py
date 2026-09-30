from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import import_csv_package
from app.commerce.repository import CommerceBenchmarkRepository
from app.db.models import Base
from app.db.migrations import apply_compatibility_migrations


def _write_package(root: Path, *, amount: str = "12.50") -> None:
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


def _dataset(root: Path):
    return import_csv_package(
        root,
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        now=datetime(2026, 1, 8, tzinfo=UTC),
    )


def _repository() -> tuple[Session, CommerceBenchmarkRepository]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, CommerceBenchmarkRepository(session)


def test_public_benchmark_round_trips_through_sqlite(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = _dataset(tmp_path)
    session, repository = _repository()
    try:
        saved = repository.save(dataset)
        loaded = repository.get(dataset.snapshot.snapshot_id)
    finally:
        session.close()

    assert saved.snapshot == dataset.snapshot
    assert loaded == dataset


def test_benchmark_repository_is_idempotent_for_same_snapshot(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = _dataset(tmp_path)
    session, repository = _repository()
    try:
        repository.save(dataset)
        saved_again = repository.save(dataset)
    finally:
        session.close()

    assert saved_again == dataset


def test_benchmark_repository_rejects_same_id_with_different_content(tmp_path: Path) -> None:
    _write_package(tmp_path)
    first = _dataset(tmp_path)
    _write_package(tmp_path, amount="99.00")
    second = _dataset(tmp_path)
    second = second.model_copy(
        update={
            "snapshot": second.snapshot.model_copy(
                update={"snapshot_id": first.snapshot.snapshot_id}
            )
        }
    )
    session, repository = _repository()
    try:
        repository.save(first)
        with pytest.raises(ValueError, match="different dataset content"):
            repository.save(second)
    finally:
        session.close()


def test_benchmark_repository_rejects_merchant_or_private_sources(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(
        tmp_path,
        mode=CommerceAnalysisMode.MERCHANT,
        source_type="merchant_upload",
    )
    session, repository = _repository()
    try:
        with pytest.raises(ValueError, match="public benchmark"):
            repository.save(dataset)
    finally:
        session.close()


def test_benchmark_repository_lists_metadata_without_dataset_records(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = _dataset(tmp_path)
    session, repository = _repository()
    try:
        repository.save(dataset)
        summaries = repository.list()
    finally:
        session.close()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.snapshot_id == dataset.snapshot.snapshot_id
    assert summary.row_counts == dataset.snapshot.row_counts
    assert "orders" not in summary.model_dump()
    assert "products" not in summary.model_dump()


def test_olist_metadata_reads_do_not_select_full_dataset(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = _dataset(tmp_path)
    dataset = dataset.model_copy(
        update={"snapshot": dataset.snapshot.model_copy(update={"schema_version": "olist-canonical-v2"})}
    )
    session, repository = _repository()
    statements: list[str] = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    try:
        repository.save(dataset)
        event.listen(session.bind, "before_cursor_execute", capture_sql)
        snapshot = repository.get_snapshot(dataset.snapshot.snapshot_id)
        analysis_source = repository.get_for_analysis(dataset.snapshot.snapshot_id)
        summaries = repository.list()
    finally:
        event.remove(session.bind, "before_cursor_execute", capture_sql)
        session.close()

    assert snapshot == dataset.snapshot
    assert analysis_source == dataset.snapshot
    assert summaries[0].snapshot_id == dataset.snapshot.snapshot_id
    assert statements and all("dataset_json" not in statement for statement in statements)


def test_existing_benchmark_database_backfills_snapshot_metadata(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = _dataset(tmp_path)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE commerce_benchmark_snapshots ("
                "snapshot_id VARCHAR(120) PRIMARY KEY, content_hash VARCHAR(128) NOT NULL, "
                "dataset_json JSON NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO commerce_benchmark_snapshots "
                "(snapshot_id, content_hash, dataset_json, created_at) "
                "VALUES (:snapshot_id, :content_hash, :dataset_json, :created_at)"
            ),
            {
                "snapshot_id": dataset.snapshot.snapshot_id,
                "content_hash": dataset.snapshot.content_hash,
                "dataset_json": json.dumps(dataset.model_dump(mode="json")),
                "created_at": dataset.snapshot.created_at.isoformat(),
            },
        )
    apply_compatibility_migrations(engine)
    apply_compatibility_migrations(engine)
    with Session(engine) as session:
        repository = CommerceBenchmarkRepository(session)
        assert repository.get_snapshot(dataset.snapshot.snapshot_id) == dataset.snapshot
        assert repository.list()[0].row_counts == dataset.snapshot.row_counts
        assert repository.get(dataset.snapshot.snapshot_id) == dataset
    engine.dispose()
