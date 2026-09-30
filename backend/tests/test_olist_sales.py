from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.sources.olist import OlistSalesFactRepository, OlistSourceAdapter
from app.commerce.warehouse import CommerceDuckDBArtifactStore
from app.commerce.metrics import TimeWindow
from app.db.session import SessionLocal, init_db
from app.main import app
from app.commerce.repository import CommerceBenchmarkRepository


def _write_olist(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at\n"
        "o-1,c-1,delivered,2018-01-01 12:00:00,2018-01-01 12:10:00\n"
        "o-2,c-2,canceled,2018-01-02 12:00:00,2018-01-02 12:10:00\n",
        encoding="utf-8",
    )
    (root / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        "o-1,1,p-1,s-1,2018-01-03 12:00:00,10.00,2.00\n"
        "o-2,1,p-1,s-2,2018-01-04 12:00:00,20.00,3.00\n",
        encoding="utf-8",
    )
    (root / "olist_products_dataset.csv").write_text(
        "product_id,product_category_name\n"
        "p-1,beleza\n",
        encoding="utf-8",
    )
    (root / "product_category_name_translation.csv").write_text(
        "product_category_name,product_category_name_english\n"
        "beleza,beauty\n",
        encoding="utf-8",
    )


def _write_olist_hot_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at\n"
        "o-prev,c-1,delivered,2018-01-01 12:00:00,2018-01-01 12:10:00\n"
        "o-current,c-2,delivered,2018-01-02 12:00:00,2018-01-02 12:10:00\n"
        "o-current-2,c-3,delivered,2018-01-02 13:00:00,2018-01-02 13:10:00\n",
        encoding="utf-8",
    )
    (root / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        "o-prev,1,p-1,s-1,2018-01-02 12:00:00,10.00,2.00\n"
        "o-current,1,p-1,s-1,2018-01-03 12:00:00,20.00,2.00\n"
        "o-current-2,1,p-2,s-2,2018-01-03 13:00:00,5.00,1.00\n",
        encoding="utf-8",
    )
    (root / "olist_products_dataset.csv").write_text(
        "product_id,product_category_name\n"
        "p-1,beleza\n"
        "p-2,cama_mesa_banho\n",
        encoding="utf-8",
    )
    (root / "product_category_name_translation.csv").write_text(
        "product_category_name,product_category_name_english\n"
        "beleza,beauty\n"
        "cama_mesa_banho,bed_bath_table\n",
        encoding="utf-8",
    )


def _import_dataset(root: Path):
    adapter = OlistSourceAdapter()
    snapshot_id = adapter.snapshot_id(root, currency="BRL")
    dataset = adapter.normalize(
        root,
        snapshot_id=snapshot_id,
        currency="BRL",
        now=datetime(2026, 1, 9, tzinfo=UTC),
    )
    return dataset, adapter


def test_olist_sales_fact_aggregates_eligible_orders_without_join_duplication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "olist"
    _write_olist(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    report = OlistSalesFactRepository(artifact_root).product_sales(
        dataset.snapshot.snapshot_id,
        TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 3, tzinfo=UTC),
        ),
    )

    assert report.included_order_count == 1
    assert report.excluded_order_count == 1
    assert len(report.metrics) == 1
    metric = report.metrics[0]
    assert metric.product_id == "p-1"
    assert metric.units_sold == Decimal("1.0000")
    assert metric.order_count == 1
    assert metric.gross_amount == Decimal("10.0000")
    assert metric.seller_count == 1
    assert metric.freight_amount == Decimal("2.0000")
    assert metric.currency == "BRL"


def test_olist_sales_endpoint_reads_shared_benchmark_fact(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "olist"
    _write_olist(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )
    monkeypatch.setenv("COMMERCE_ARTIFACT_ROOT", str(artifact_root))
    init_db()
    with SessionLocal() as db:
        CommerceBenchmarkRepository(db).save(dataset)

    with TestClient(app) as client:
        response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/sales",
            params={
                "start": "2018-01-01T00:00:00Z",
                "end": "2018-01-03T00:00:00Z",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["included_order_count"] == 1
    assert body["excluded_order_count"] == 1
    assert body["metrics"][0]["product_id"] == "p-1"
    assert Decimal(str(body["metrics"][0]["gross_amount"])) == Decimal("10.0000")


def test_olist_hot_products_explain_growth_against_equal_baseline(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    report = OlistSalesFactRepository(artifact_root).hot_products(
        dataset.snapshot.snapshot_id,
        TimeWindow(
            start=datetime(2018, 1, 2, tzinfo=UTC),
            end=datetime(2018, 1, 3, tzinfo=UTC),
        ),
        TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 2, tzinfo=UTC),
        ),
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.rank == 1
    assert candidate.product_id == "p-1"
    assert candidate.labels == ("volume_leader", "revenue_leader", "momentum")
    assert candidate.confidence == "high"
    assert candidate.trend.previous is not None
    assert candidate.trend.gross_amount_growth_rate == Decimal("1.0000")
    assert "相对等长基线窗口增长至少 20%" in candidate.evidence


def test_olist_product_trends_keep_new_products_visible(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    report = OlistSalesFactRepository(artifact_root).product_trends(
        dataset.snapshot.snapshot_id,
        TimeWindow(
            start=datetime(2018, 1, 2, tzinfo=UTC),
            end=datetime(2018, 1, 3, tzinfo=UTC),
        ),
        TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 2, tzinfo=UTC),
        ),
    )

    by_product = {trend.product_id: trend for trend in report.trends}
    assert set(by_product) == {"p-1", "p-2"}
    assert by_product["p-1"].gross_amount_growth_rate == Decimal("1.0000")
    assert by_product["p-2"].current is not None
    assert by_product["p-2"].previous is None
