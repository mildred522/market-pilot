from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.commerce.contracts import (
    CommerceAnalysisMode,
    CommerceInteraction,
    CommerceScope,
    InteractionMode,
)
from app.commerce.providers import OlistDuckDBFactProvider
from app.commerce.plan import CommercePlanRequest, CommercePlanService
from app.commerce.sources.olist import OlistSalesFactRepository, OlistSourceAdapter
from app.commerce.warehouse import CommerceDuckDBArtifactStore
from app.commerce.metrics import ItemLevel, OlistComparisonWindows, TimeWindow
from app.commerce.talk import CommerceTalkRequest, CommerceTalkService
from scripts.evaluate_olist_benchmark import _rolling_holdout_backtest, evaluate_olist_benchmark
from scripts.evaluate_olist_cases import (
    _check_hot_products,
    _check_product_trends,
    _check_sales,
    _source_sales,
    evaluate_olist_cases,
)
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


def _write_olist_hot_fixture(
    root: Path, *, current_count: int = 4, current_price: str = "20.00", new_count: int = 3
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    baseline_orders = [(f"o-prev-{index}", "p-1", "10.00") for index in range(3)]
    current_orders = [(f"o-current-{index}", "p-1", current_price) for index in range(current_count)]
    current_orders += [(f"o-new-{index}", "p-2", "5.00") for index in range(new_count)]
    (root / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at\n"
        + "".join(
            f"{order_id},c-{order_id},delivered,2018-01-{day} 12:00:00,2018-01-{day} 12:10:00\n"
            for day, orders in (("01", baseline_orders), ("02", current_orders))
            for order_id, _, _ in orders
        ),
        encoding="utf-8",
    )
    (root / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        + "".join(
            f"{order_id},1,{product_id},s-{product_id},2018-01-03 12:00:00,{price},2.00\n"
            for order_id, product_id, price in baseline_orders + current_orders
        ),
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


def test_olist_category_sales_counts_distinct_orders_and_sellers_within_category(
    tmp_path: Path,
) -> None:
    source = tmp_path / "olist"
    source.mkdir()
    (source / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp\n"
        "o-1,c-1,delivered,2018-01-01 12:00:00\n"
        "o-2,c-2,approved,2018-01-01 13:00:00\n"
        "o-3,c-3,canceled,2018-01-01 14:00:00\n"
        "o-4,c-4,delivered,2018-01-01 15:00:00\n",
        encoding="utf-8",
    )
    (source / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,price,freight_value\n"
        "o-1,1,p-1,s-1,10.00,1.00\n"
        "o-1,2,p-2,s-1,20.00,1.00\n"
        "o-1,3,p-3,s-1,5.00,1.00\n"
        "o-2,1,p-1,s-1,10.00,1.00\n"
        "o-3,1,p-1,s-2,100.00,1.00\n"
        "o-4,1,p-4,s-2,7.00,1.00\n",
        encoding="utf-8",
    )
    (source / "olist_products_dataset.csv").write_text(
        "product_id,product_category_name\n"
        "p-1,beauty\n"
        "p-2,beauty\n"
        "p-3,tools\n"
        "p-4,\n",
        encoding="utf-8",
    )
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    report = OlistSalesFactRepository(artifact_root).category_sales(
        dataset.snapshot.snapshot_id,
        TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 2, tzinfo=UTC),
        ),
    )

    assert report.included_order_count == 3
    assert report.excluded_order_count == 1
    assert [category.category_name for category in report.categories] == ["beauty", None, "tools"]
    beauty, uncategorized, tools = report.categories
    assert (beauty.product_count, beauty.units_sold, beauty.order_count, beauty.gross_amount, beauty.seller_count) == (
        2, Decimal("3.0000"), 2, Decimal("40.0000"), 1
    )
    assert (tools.product_count, tools.order_count, tools.gross_amount, tools.seller_count) == (
        1, 1, Decimal("5.0000"), 1
    )
    assert (uncategorized.product_count, uncategorized.gross_amount, uncategorized.currency) == (
        1, Decimal("7.0000"), "BRL"
    )
    assert sum(category.order_count for category in report.categories) > report.included_order_count


def test_olist_category_trends_use_shared_category_facts(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    provider = OlistDuckDBFactProvider(
        dataset.snapshot.snapshot_id, OlistSalesFactRepository(artifact_root)
    )
    trends = provider.category_trends(
        TimeWindow(start=datetime(2018, 1, 1, tzinfo=UTC), end=datetime(2018, 1, 2, tzinfo=UTC)),
        TimeWindow(start=datetime(2018, 1, 2, tzinfo=UTC), end=datetime(2018, 1, 3, tzinfo=UTC)),
    )

    by_name = {trend.category_name: trend for trend in trends.trends}
    assert by_name["beauty"].previous.gross_amount == Decimal("30.0000")
    assert by_name["beauty"].current.gross_amount == Decimal("80.0000")
    assert by_name["beauty"].gross_amount_growth_rate == Decimal("50") / Decimal("30")
    assert by_name["bed_bath_table"].previous is None
    assert by_name["bed_bath_table"].gross_amount_growth_rate is None


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

    def fail_full_dataset_read(_repository, _snapshot_id):
        raise AssertionError("Olist endpoint must not hydrate the full SQLite dataset")

    monkeypatch.setattr(CommerceBenchmarkRepository, "get", fail_full_dataset_read)

    with TestClient(app) as client:
        listing = client.get("/commerce/benchmarks")
        response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/sales",
            params={
                "start": "2018-01-01T00:00:00Z",
                "end": "2018-01-03T00:00:00Z",
            },
        )
        categories_response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/category-sales",
            params={
                "start": "2018-01-01T00:00:00Z",
                "end": "2018-01-03T00:00:00Z",
            },
        )
        windows_response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/comparison-windows"
        )
        trends_response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/trends",
            params={"start": "2018-01-01T00:00:00", "end": "2018-01-03T00:00:00"},
        )
        category_trends_response = client.get(
            f"/commerce/benchmarks/{dataset.snapshot.snapshot_id}/category-trends",
            params={"start": "2018-01-01T00:00:00", "end": "2018-01-03T00:00:00"},
        )

    assert listing.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["included_order_count"] == 1
    assert body["excluded_order_count"] == 1
    assert body["metrics"][0]["product_id"] == "p-1"
    assert Decimal(str(body["metrics"][0]["gross_amount"])) == Decimal("10.0000")
    assert categories_response.status_code == 200
    assert categories_response.json()["categories"][0]["category_name"] == "beauty"
    assert Decimal(str(categories_response.json()["categories"][0]["gross_amount"])) == Decimal("10.0000")
    assert windows_response.status_code == 200
    assert windows_response.json()["selection_method"] == "split_coverage"
    assert windows_response.json()["warning"]
    assert trends_response.status_code == 200
    assert category_trends_response.status_code == 200
    assert category_trends_response.json()["snapshot_id"] == dataset.snapshot.snapshot_id
    assert category_trends_response.json()["trends"][0]["category_name"] == "beauty"


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
    assert candidate.trend.gross_amount_growth_rate.quantize(Decimal("0.0001")) == Decimal("1.6667")
    assert any("销量和销售额均增长至少 20%" in item for item in candidate.evidence)


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
    assert by_product["p-1"].gross_amount_growth_rate.quantize(Decimal("0.0001")) == Decimal("1.6667")
    assert by_product["p-2"].current is not None
    assert by_product["p-2"].previous is None


def test_olist_selection_recommendations_keep_actions_evidence_based(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    report = OlistSalesFactRepository(artifact_root).selection_recommendations(
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

    assert [item.product_id for item in report.recommendations] == ["p-1", "p-2"]
    assert report.recommendations[0].recommendation_type == "verify_growth"
    assert report.recommendations[0].priority == "medium"
    assert "销售额增长率 +166.7%" in report.recommendations[0].evidence
    assert "增长未必延续" in report.recommendations[0].risk_flags
    assert "未确认持续性前不扩大备货" in report.recommendations[0].action
    assert report.recommendations[1].recommendation_type == "validate_new_product"
    assert "缺少历史基线" in report.recommendations[1].risk_flags


def test_olist_selection_ranks_observed_change_across_action_types(
    tmp_path: Path,
) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    orders_file = source / "olist_orders_dataset.csv"
    orders_file.write_text(
        orders_file.read_text(encoding="utf-8")
        + "".join(
            f"o-lost-{index},c-lost-{index},delivered,2018-01-01 12:00:00,2018-01-01 12:10:00\n"
            for index in range(5)
        ),
        encoding="utf-8",
    )
    items_file = source / "olist_order_items_dataset.csv"
    items_file.write_text(
        items_file.read_text(encoding="utf-8")
        + "".join(
            f"o-lost-{index},1,p-3,s-3,2018-01-03 12:00:00,40.00,2.00\n"
            for index in range(5)
        ),
        encoding="utf-8",
    )
    products_file = source / "olist_products_dataset.csv"
    products_file.write_text(
        products_file.read_text(encoding="utf-8") + "p-3,beleza\n",
        encoding="utf-8",
    )
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )

    report = OlistSalesFactRepository(artifact_root).selection_recommendations(
        dataset.snapshot.snapshot_id,
        TimeWindow(start=datetime(2018, 1, 2), end=datetime(2018, 1, 3)),
        TimeWindow(start=datetime(2018, 1, 1), end=datetime(2018, 1, 2)),
    )

    assert [item.product_id for item in report.recommendations] == ["p-3", "p-1", "p-2"]
    assert {item.priority for item in report.recommendations} == {"medium"}


def test_olist_price_only_growth_does_not_trigger_momentum_or_expansion(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source, current_count=3, new_count=1)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    repository = OlistSalesFactRepository(artifact_root)
    current = TimeWindow(start=datetime(2018, 1, 2), end=datetime(2018, 1, 3))
    baseline = TimeWindow(start=datetime(2018, 1, 1), end=datetime(2018, 1, 2))

    hot = repository.hot_products(dataset.snapshot.snapshot_id, current, baseline)
    selection = repository.selection_recommendations(dataset.snapshot.snapshot_id, current, baseline)

    assert len(hot.candidates) == 1
    assert "momentum" not in hot.candidates[0].labels
    assert not selection.recommendations


def test_olist_low_sample_does_not_create_hot_candidate_or_action(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    repository = OlistSalesFactRepository(artifact_root)
    current = TimeWindow(start=datetime(2018, 1, 1), end=datetime(2018, 1, 3))
    baseline = TimeWindow(start=datetime(2017, 12, 30), end=datetime(2018, 1, 1))

    assert not repository.hot_products(dataset.snapshot.snapshot_id, current, baseline).candidates
    assert not repository.selection_recommendations(
        dataset.snapshot.snapshot_id, current, baseline
    ).recommendations


def test_olist_comparison_windows_skip_sparse_tail(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    orders = [("edge", "2018-05-31 12:00:00")]
    orders += [
        (
            f"{month}-{index}",
            f"2018-{month}-{(10 if month == '06' else 7) + index // 6:02d} 12:00:00",
        )
        for month in ("06", "07", "08")
        for index in range(24)
    ]
    orders += [("sparse-september", "2018-09-15 12:00:00"), ("tail", "2018-10-01 12:00:00")]
    (source / "olist_orders_dataset.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at\n"
        + "".join(
            f"{order_id},c-{order_id},delivered,{timestamp},{timestamp}\n"
            for order_id, timestamp in orders
        ),
        encoding="utf-8",
    )
    (source / "olist_order_items_dataset.csv").write_text(
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value\n"
        + "".join(
            f"{order_id},1,p-1,s-1,{timestamp},10.00,2.00\n"
            for order_id, timestamp in orders
        ),
        encoding="utf-8",
    )
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )

    windows = OlistSalesFactRepository(artifact_root).comparison_windows(
        dataset.snapshot.snapshot_id
    )

    assert windows.selection_method == "latest_dense_28d"
    assert windows.warning is None
    assert windows.current_window.start == datetime(2018, 8, 4)
    assert windows.current_window.end == datetime(2018, 9, 1)
    assert windows.baseline_window.start == datetime(2018, 7, 7)
    assert windows.baseline_order_count == 24
    assert windows.current_order_count == 24

    evaluation = evaluate_olist_benchmark(
        source, artifact_root=artifact_root, currency="BRL"
    )
    assert evaluation["backtest"]["status"] == "completed"
    assert evaluation["backtest"]["fold_count"] == 1
    assert evaluation["backtest"]["folds"][0]["order_counts"] == [24, 24, 24]


def test_olist_comparison_windows_warn_when_no_dense_months(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )

    windows = OlistSalesFactRepository(artifact_root).comparison_windows(
        dataset.snapshot.snapshot_id
    )

    assert windows.selection_method == "split_coverage"
    assert windows.warning
    assert windows.baseline_window.end == windows.current_window.start
    assert windows.current_window.end - windows.current_window.start == (
        windows.baseline_window.end - windows.baseline_window.start
    )
    assert windows.baseline_order_count == 3
    assert windows.current_order_count == 7


def test_olist_talk_and_plan_api_read_metadata_instead_of_full_dataset(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    monkeypatch.setenv("COMMERCE_ARTIFACT_ROOT", str(artifact_root))
    init_db()
    with SessionLocal() as db:
        CommerceBenchmarkRepository(db).save(dataset)

    def fail_full_dataset_read(_repository, _snapshot_id):
        raise AssertionError("Olist analysis must not hydrate the full SQLite dataset")

    monkeypatch.setattr(CommerceBenchmarkRepository, "get", fail_full_dataset_read)
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "Olist 轻量分析", "stage": "operating"}
        ).json()
        scope = {
            "mode": "benchmark",
            "project_id": project["id"],
            "snapshot_id": dataset.snapshot.snapshot_id,
        }
        payload = {
            "question": "商品销量和趋势如何？",
            "interaction": {"mode": "talk", "scope": scope},
            "previous_window": {
                "start": "2018-01-01T00:00:00", "end": "2018-01-02T00:00:00"
            },
            "current_window": {
                "start": "2018-01-02T00:00:00", "end": "2018-01-03T00:00:00"
            },
            "item_level": "product",
        }
        talk_response = client.post("/commerce/talk", json=payload)
        payload["question"] = "规划商品经营动作"
        payload["interaction"] = {"mode": "plan", "scope": scope}
        plan_response = client.post("/commerce/plans", json=payload)

    assert talk_response.status_code == 200
    assert talk_response.json()["status"] == "completed"
    assert plan_response.status_code == 201
    assert plan_response.json()["steps"]


def test_talk_reads_olist_sales_through_duckdb_fact_provider(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    request = CommerceTalkRequest(
        question="这个窗口卖了哪些商品？",
        interaction=CommerceInteraction(
            mode=InteractionMode.TALK,
            scope=CommerceScope(
                mode=CommerceAnalysisMode.BENCHMARK,
                project_id=1,
                snapshot_id=dataset.snapshot.snapshot_id,
            ),
        ),
        previous_window=TimeWindow(
            start=datetime(2017, 12, 30, tzinfo=UTC),
            end=datetime(2018, 1, 1, tzinfo=UTC),
        ),
        current_window=TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 3, tzinfo=UTC),
        ),
    )
    response = CommerceTalkService().answer(
        request,
        dataset,
        provider=OlistDuckDBFactProvider(
            snapshot_id=dataset.snapshot.snapshot_id,
            repository=OlistSalesFactRepository(artifact_root),
        ),
    )

    assert response.status == "completed"
    assert response.executions[0].status == "completed"
    assert response.executions[0].data is not None
    assert Decimal(str(response.executions[0].data["metrics"][0]["gross_amount"])) == Decimal("10.0000")


def test_plan_reads_olist_selection_recommendations(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    dataset, adapter = _import_dataset(source)
    artifact_root = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifact_root).write(
        dataset,
        staging_tables=adapter.staging_tables(source),
    )

    request = CommercePlanRequest(
        question="规划下一窗口的商品经营动作",
        interaction=CommerceInteraction(
            mode=InteractionMode.PLAN,
            scope=CommerceScope(
                mode=CommerceAnalysisMode.BENCHMARK,
                project_id=1,
                snapshot_id=dataset.snapshot.snapshot_id,
            ),
        ),
        previous_window=TimeWindow(
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2018, 1, 2, tzinfo=UTC),
        ),
        current_window=TimeWindow(
            start=datetime(2018, 1, 2, tzinfo=UTC),
            end=datetime(2018, 1, 3, tzinfo=UTC),
        ),
    )
    draft = CommercePlanService().draft(
        request,
        dataset,
        provider=OlistDuckDBFactProvider(
            snapshot_id=dataset.snapshot.snapshot_id,
            repository=OlistSalesFactRepository(artifact_root),
        ),
    )

    assert draft.status.value == "draft"
    assert draft.steps
    assert "再决定是否试验" in draft.steps[0].success_signal

    with pytest.raises(ValueError, match="DuckDB fact provider"):
        CommercePlanService().draft(request, dataset.snapshot)


def test_olist_benchmark_evaluation_reports_full_fact_chain(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)

    result = evaluate_olist_benchmark(
        source,
        artifact_root=tmp_path / "artifacts",
        currency="BRL",
    )

    assert result["ready"] is True
    assert result["snapshot"]["schema_version"] == "olist-canonical-v2"
    assert result["sales"]["product_count"] == 2
    assert result["category_sales"]["category_count"] == 2
    assert result["category_sales"]["product_totals_reconciled"] is True
    assert result["trends"]["new_item_count"] == 1
    assert result["hot_products"]["candidate_count"] == 1
    assert result["selection"]["type_counts"]["verify_growth"] == 1
    assert result["backtest"]["status"] == "unavailable"


def test_independent_olist_cases_compare_raw_sales_and_refusal(tmp_path: Path) -> None:
    source = tmp_path / "olist"
    _write_olist_hot_fixture(source)
    with (source / "olist_orders_dataset.csv").open("a", encoding="utf-8") as orders:
        orders.write("o-later,c-later,delivered,2018-01-04 12:00:00,2018-01-04 12:10:00\n")
    with (source / "olist_order_items_dataset.csv").open("a", encoding="utf-8") as items:
        items.write("o-later,1,p-1,s-p-1,2018-01-05 12:00:00,30.00,2.00\n")
    dataset, adapter = _import_dataset(source)
    artifacts = tmp_path / "artifacts"
    CommerceDuckDBArtifactStore(artifacts).write(
        dataset, staging_tables=adapter.staging_tables(source)
    )
    casebook = tmp_path / "cases.json"
    casebook.write_text(
        '{"version":1,"windows":{"one":{"previous":'
        '{"start":"2018-01-01T12:00:00","end":"2018-01-02T12:00:00"},'
        '"current":{"start":"2018-01-02T12:00:00","end":"2018-01-03T12:00:00"}}},'
        '"cases":[{"id":"sales","window":"one","question":"商品销售如何？",'
        '"expected_status":"completed","expected_tools":["commerce_analyze_product_sales"]},'
        '{"id":"trends","window":"one","question":"商品增长趋势如何？",'
        '"expected_status":"completed","expected_tools":'
        '["commerce_compare_product_trends","commerce_analyze_product_sales"]},'
        '{"id":"scope","window":"one","question":"给我别的项目销售",'
        '"expected_status":"insufficient_data","expected_tools":[]}]}'
    )

    result = evaluate_olist_cases(
        source, cases_path=casebook, artifact_root=artifacts, currency="BRL"
    )

    assert result["automated_pass"] is True
    assert result["human_review"] == "pending"
    assert all(case["passed"] for case in result["cases"])
    assert _check_sales(
        {"included_order_count": 1, "excluded_order_count": 1, "metrics": []},
        {"included": 0, "excluded": 1, "products": {}},
    ) == ["included order count differs from raw orders"]

    previous_window = TimeWindow(start=datetime(2018, 1, 1, 12), end=datetime(2018, 1, 2, 12))
    current_window = TimeWindow(start=datetime(2018, 1, 2, 12), end=datetime(2018, 1, 3, 12))
    previous_source = _source_sales(source, previous_window)
    current_source = _source_sales(source, current_window)
    report = OlistSalesFactRepository(artifacts).product_trends(
        dataset.snapshot.snapshot_id, current_window, previous_window
    )
    data = {"items": [trend.model_dump(mode="json") for trend in report.trends]}
    assert _check_product_trends(data, previous_source, current_source) == []
    data["items"][0]["gross_amount_growth_rate"] = "0"
    assert any("gross_amount_growth_rate" in failure for failure in _check_product_trends(
        data, previous_source, current_source
    ))
    data["items"][0]["previous"]["gross_amount"] = "999"
    assert any("previous differs" in failure for failure in _check_product_trends(
        data, previous_source, current_source
    ))
    data["items"][0]["category_name"] = "wrong"
    assert any("trend grain" in failure for failure in _check_product_trends(
        data, previous_source, current_source
    ))
    assert any("product union" in failure for failure in _check_product_trends(
        {"items": []}, previous_source, current_source
    ))

    sku_report = OlistSalesFactRepository(artifacts).product_trends(
        dataset.snapshot.snapshot_id,
        current_window,
        previous_window,
        item_level=ItemLevel.SKU,
    )
    sku_data = {"items": [trend.model_dump(mode="json") for trend in sku_report.trends]}
    assert _check_product_trends(
        sku_data, previous_source, current_source, item_level="sku"
    ) == []

    hot_report = OlistSalesFactRepository(artifacts).hot_products(
        dataset.snapshot.snapshot_id, current_window, previous_window
    )
    hot_data = {"candidates": [candidate.model_dump(mode="json") for candidate in hot_report.candidates]}
    assert _check_hot_products(hot_data, previous_source, current_source) == []
    hot_data["candidates"][0]["labels"] = ["revenue_leader"]
    assert any("hot candidate" in failure for failure in _check_hot_products(
        hot_data, previous_source, current_source
    ))


def test_olist_holdout_backtest_counts_growth_and_disappearance() -> None:
    class FactRepository:
        def product_sales(self, _snapshot_id, window):
            units_by_start = {
                datetime(2018, 1, 1): 3,
                datetime(2018, 1, 29): 5,
                datetime(2018, 2, 26): 6,
            }
            units = units_by_start[window.start]
            metrics = (
                SimpleNamespace(
                    item_id="growing", units_sold=Decimal(units),
                    gross_amount=Decimal(units * 10),
                ),
            )
            return SimpleNamespace(included_order_count=24, metrics=metrics)

        def selection_recommendations(self, _snapshot_id, _observed, _baseline):
            return SimpleNamespace(
                recommendations=(
                    SimpleNamespace(
                        item_id="growing", recommendation_type="verify_growth",
                        current=SimpleNamespace(
                            units_sold=Decimal(5), gross_amount=Decimal(50)
                        ),
                    ),
                    SimpleNamespace(
                        item_id="disappeared", recommendation_type="review_decline",
                        current=SimpleNamespace(
                            units_sold=Decimal(5), gross_amount=Decimal(50)
                        ),
                    ),
                    SimpleNamespace(
                        item_id="new", recommendation_type="validate_new_product",
                        current=SimpleNamespace(
                            units_sold=Decimal(5), gross_amount=Decimal(50)
                        ),
                    ),
                )
            )

    comparison = OlistComparisonWindows(
        snapshot_id="fixture",
        baseline_window=TimeWindow(
            start=datetime(2018, 1, 29), end=datetime(2018, 2, 26)
        ),
        current_window=TimeWindow(
            start=datetime(2018, 2, 26), end=datetime(2018, 3, 26)
        ),
        selection_method="latest_dense_28d",
        baseline_order_count=24,
        current_order_count=24,
    )
    result = _rolling_holdout_backtest(
        FactRepository(), "fixture", comparison,
        TimeWindow(start=datetime(2018, 1, 1), end=datetime(2018, 3, 27)),
    )

    assert result["fold_count"] == 1
    assert result["action_counts"] == {
        "verify_growth": 1, "review_decline": 1, "validate_new_product": 1
    }
    assert result["next_window_present_counts"] == {
        "review_decline": 0, "verify_growth": 1, "validate_new_product": 0
    }
    assert result["directional_eligible_counts"] == {"review_decline": 1, "verify_growth": 1}
    assert result["same_direction_counts"] == {"review_decline": 1, "verify_growth": 1}
