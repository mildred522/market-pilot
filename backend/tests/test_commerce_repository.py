from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import import_csv_package
from app.commerce.repository import CommerceBenchmarkRepository
from app.db.models import Base


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
