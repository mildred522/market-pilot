import pytest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from pydantic import ValidationError

from app.commerce.capabilities import check_capability
from app.commerce.canonical.models import OrderItemRecord, ProductRecord
from app.commerce.contracts import (
    CommerceAnalysisMode,
    CommerceCapability,
    CommerceInteraction,
    CommerceScope,
    InteractionMode,
)
from app.commerce.snapshot import CommerceSnapshot
from app.commerce.ingestion import CommerceImportError, import_csv_package
from app.commerce.metrics import (
    TimeWindow,
    compare_sales_windows,
    compute_sales_report,
    discover_hot_products,
)
from app.commerce.metrics.contracts import ItemLevel
from app.commerce.tools import (
    CommerceToolContext,
    execute_commerce_talk_tools,
    validate_talk_tool_selection,
)
from app.commerce.talk import (
    CommerceTalkRequest,
    CommerceTalkService,
    route_talk_question,
)


def test_merchant_scope_requires_store() -> None:
    with pytest.raises(ValidationError):
        CommerceScope(mode=CommerceAnalysisMode.MERCHANT, project_id=1)


def test_benchmark_scope_can_be_project_scoped_without_store() -> None:
    scope = CommerceScope(mode=CommerceAnalysisMode.BENCHMARK, project_id=1)
    interaction = CommerceInteraction(
        mode=InteractionMode.TALK,
        scope=scope,
        requested_capabilities=(CommerceCapability.SALES,),
    )

    assert interaction.scope.mode is CommerceAnalysisMode.BENCHMARK
    assert interaction.requested_capabilities == (CommerceCapability.SALES,)


def test_canonical_order_item_keeps_normalized_amounts() -> None:
    item = OrderItemRecord(
        order_id="order-1",
        order_item_id="1",
        sku_id="sku-1",
        quantity=2,
        unit_price=Decimal("12.50"),
        currency="BRL",
    )

    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("12.50")


def test_snapshot_rejects_invalid_period_and_is_immutable() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        CommerceSnapshot(
            snapshot_id="snap-1",
            mode=CommerceAnalysisMode.BENCHMARK,
            source_type="public_dataset",
            schema_version="v1",
            content_hash="hash",
            created_at=now,
            period_start=now,
            period_end=now - timedelta(seconds=1),
        )

    snapshot = CommerceSnapshot(
        snapshot_id="snap-1",
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        schema_version="v1",
        content_hash="hash",
        created_at=now,
    )
    with pytest.raises(ValidationError):
        snapshot.snapshot_id = "snap-2"


def test_sales_capability_reports_partial_catalog_support() -> None:
    availability = check_capability(
        CommerceCapability.SALES,
        {CommerceCapability.SALES},
    )

    assert availability.status == "partial"
    assert availability.missing == (CommerceCapability.CATALOG,)


def _write_package(root: Path, *, orphan_item: bool = False) -> None:
    (root / "products.csv").write_text(
        "product_id,product_title,category_name\np-1,Demo Product,Demo\n",
        encoding="utf-8",
    )
    (root / "skus.csv").write_text(
        "sku_id,product_id,sku_code\nsku-1,p-1,DEMO-1\n",
        encoding="utf-8",
    )
    (root / "orders.csv").write_text(
        "order_id,ordered_at,order_status,currency\no-1,2026-01-01T12:00:00+00:00,fulfilled,BRL\n",
        encoding="utf-8",
    )
    sku_id = "missing-sku" if orphan_item else "sku-1"
    (root / "order_items.csv").write_text(
        f"order_id,order_item_id,sku_id,quantity,unit_price,currency\no-1,1,{sku_id},2,12.50,BRL\n",
        encoding="utf-8",
    )


def test_csv_package_import_creates_hashed_snapshot(tmp_path: Path) -> None:
    _write_package(tmp_path)

    dataset = import_csv_package(
        tmp_path,
        mode=CommerceAnalysisMode.BENCHMARK,
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert dataset.snapshot.snapshot_id.startswith("csv-")
    assert dataset.snapshot.row_counts["orders"] == 1
    assert dataset.order_items[0].unit_price == Decimal("12.50")
    assert dataset.quality.blocking is False


def test_csv_package_import_rejects_orphan_reference(tmp_path: Path) -> None:
    _write_package(tmp_path, orphan_item=True)

    with pytest.raises(CommerceImportError) as error:
        import_csv_package(tmp_path, mode=CommerceAnalysisMode.BENCHMARK)

    assert any(issue.code == "orphan_reference" for issue in error.value.report.issues)


def test_sales_metrics_and_trends_are_deterministic(tmp_path: Path) -> None:
    _write_package(tmp_path)
    (tmp_path / "orders.csv").write_text(
        "order_id,ordered_at,order_status,currency\n"
        "o-1,2026-01-01T12:00:00+00:00,fulfilled,BRL\n"
        "o-2,2026-01-08T12:00:00+00:00,fulfilled,BRL\n"
        "o-3,2026-01-08T13:00:00+00:00,cancelled,BRL\n",
        encoding="utf-8",
    )
    (tmp_path / "order_items.csv").write_text(
        "order_id,order_item_id,sku_id,quantity,unit_price,currency\n"
        "o-1,1,sku-1,2,12.50,BRL\n"
        "o-2,1,sku-1,3,12.50,BRL\n"
        "o-3,1,sku-1,10,12.50,BRL\n",
        encoding="utf-8",
    )
    dataset = import_csv_package(tmp_path, mode=CommerceAnalysisMode.BENCHMARK)
    previous = TimeWindow(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 8, tzinfo=UTC))
    current = TimeWindow(start=datetime(2026, 1, 8, tzinfo=UTC), end=datetime(2026, 1, 15, tzinfo=UTC))

    report = compute_sales_report(dataset, current, item_level=ItemLevel.SKU)
    trends = compare_sales_windows(dataset, previous, current)
    candidates = discover_hot_products(dataset, previous, current, min_orders=1)

    assert report.metrics[0].units_sold == Decimal("3")
    assert report.metrics[0].item_gross_amount == Decimal("37.50")
    assert report.excluded_order_ids == ("o-3",)
    assert trends[0].gross_amount_growth_rate == Decimal("0.5")
    assert "emerging_product" in candidates[0].labels


def test_talk_tools_execute_read_only_sales_analysis(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(tmp_path, mode=CommerceAnalysisMode.BENCHMARK)
    previous = TimeWindow(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 8, tzinfo=UTC))
    current = TimeWindow(start=datetime(2026, 1, 8, tzinfo=UTC), end=datetime(2026, 1, 15, tzinfo=UTC))
    context = CommerceToolContext(
        interaction=CommerceInteraction(
            mode=InteractionMode.TALK,
            scope=CommerceScope(mode=CommerceAnalysisMode.BENCHMARK, project_id=1),
        ),
        dataset=dataset,
        previous_window=previous,
        current_window=current,
    )

    batch = execute_commerce_talk_tools(
        ["commerce_analyze_product_sales"],
        context,
    )

    assert batch.executions[0].status == "completed"
    assert batch.executions[0].evidence[0].startswith("snapshot:csv-")


def test_talk_policy_rejects_unknown_or_plan_tools() -> None:
    with pytest.raises(ValueError):
        validate_talk_tool_selection(["commerce_create_plan"])


def test_talk_request_routes_to_read_only_tools(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(tmp_path, mode=CommerceAnalysisMode.BENCHMARK)
    previous = TimeWindow(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 8, tzinfo=UTC))
    current = TimeWindow(start=datetime(2026, 1, 8, tzinfo=UTC), end=datetime(2026, 1, 15, tzinfo=UTC))
    request = CommerceTalkRequest(
        question="最近哪些商品增长较快？",
        interaction=CommerceInteraction(
            mode=InteractionMode.TALK,
            scope=CommerceScope(mode=CommerceAnalysisMode.BENCHMARK, project_id=1),
        ),
        previous_window=previous,
        current_window=current,
    )

    response = CommerceTalkService().answer(request, dataset)

    assert route_talk_question(request.question) == [
        "commerce_compare_product_trends",
        "commerce_analyze_product_sales",
    ]
    assert response.status == "completed"
    assert response.intent.value == "mixed"
    assert all("plan" not in tool for tool in response.selected_tools)
