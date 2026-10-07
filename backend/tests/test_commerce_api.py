from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import auth_is_disabled
from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.ingestion import import_csv_package
from app.commerce.repository import CommerceBenchmarkRepository
from app.db.models import Base, CommercePlan
from app.db.session import SessionLocal, get_db, init_db
from app.main import app


def _write_package(root: Path) -> None:
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
        "o-1,1,sku-1,2,12.50,BRL\n",
        encoding="utf-8",
    )


def _talk_payload(
    project_id: int,
    snapshot_id: str,
    *,
    mode: str = "benchmark",
    store_id: int | None = None,
) -> dict[str, object]:
    scope: dict[str, object] = {
        "mode": mode,
        "project_id": project_id,
        "snapshot_id": snapshot_id,
    }
    if store_id is not None:
        scope["store_id"] = store_id
    return {
        "question": "哪些商品销售最好？",
        "interaction": {
            "mode": "talk",
            "scope": scope,
        },
        "previous_window": {
            "start": "2025-12-25T00:00:00Z",
            "end": "2026-01-01T00:00:00Z",
        },
        "current_window": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-08T00:00:00Z",
        },
        "item_level": "sku",
    }


def _plan_payload(project_id: int, snapshot_id: str) -> dict[str, object]:
    payload = _talk_payload(project_id, snapshot_id)
    payload["question"] = "为热销和增长商品制定未来两周的经营计划"
    payload["interaction"] = {
        "mode": "plan",
        "scope": {
            "mode": "benchmark",
            "project_id": project_id,
            "snapshot_id": snapshot_id,
        },
    }
    return payload


def _persist_benchmark(dataset) -> None:
    init_db()
    with SessionLocal() as db:
        CommerceBenchmarkRepository(db).save(dataset)


def test_benchmark_commerce_talk_uses_registered_snapshot(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(
        tmp_path,
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        now=datetime(2026, 1, 8, tzinfo=UTC),
    )
    _persist_benchmark(dataset)

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "电商基准项目", "stage": "operating"},
        ).json()
        response = client.post(
            "/commerce/talk",
            json=_talk_payload(project["id"], dataset.snapshot.snapshot_id),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["intent"] == "sales"
    assert body["executions"][0]["evidence"] == [
        f"snapshot:{dataset.snapshot.snapshot_id}",
        f"project:{project['id']}",
    ]


def test_benchmark_list_is_empty_when_no_snapshot_is_imported() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_db() -> Generator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.get("/commerce/benchmarks")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == []


def test_commerce_benchmark_api_requires_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "false")

    with TestClient(app) as client:
        listing = client.get("/commerce/benchmarks")
        talk = client.post(
            "/commerce/talk",
            json=_talk_payload(1, "not-registered"),
        )

    assert listing.status_code == 401
    assert listing.headers["www-authenticate"] == "Session"
    assert talk.status_code == 401
    assert talk.json()["detail"] == "authentication required"


def test_benchmark_list_returns_metadata_only(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(
        tmp_path,
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        now=datetime(2026, 1, 8, tzinfo=UTC),
    )
    _persist_benchmark(dataset)

    with TestClient(app) as client:
        response = client.get("/commerce/benchmarks")

    assert response.status_code == 200
    body = response.json()
    summary = next(item for item in body if item["snapshot_id"] == dataset.snapshot.snapshot_id)
    assert summary["row_counts"] == dataset.snapshot.row_counts
    assert "products" not in summary
    assert "orders" not in summary


def test_commerce_talk_requires_registered_snapshot() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "缺少快照项目", "stage": "operating"},
        ).json()
        response = client.post(
            "/commerce/talk",
            json=_talk_payload(project["id"], "csv-not-registered"),
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "commerce_snapshot_not_found"


def test_merchant_commerce_talk_does_not_claim_store_authorization() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "商家项目", "stage": "operating"},
        ).json()
        response = client.post(
            "/commerce/talk",
            json=_talk_payload(
                project["id"],
                "merchant-snapshot",
                mode="merchant",
                store_id=1,
            ),
        )

    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "merchant_scope_not_ready"


def test_admin_can_create_read_and_approve_commerce_plan(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(
        tmp_path,
        mode=CommerceAnalysisMode.BENCHMARK,
        source_type="public_dataset",
        now=datetime(2026, 1, 8, tzinfo=UTC),
    )
    _persist_benchmark(dataset)

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "电商计划项目", "stage": "operating"},
        ).json()
        created = client.post(
            "/commerce/plans",
            json=_plan_payload(project["id"], dataset.snapshot.snapshot_id),
        )

        assert created.status_code == 201
        plan = created.json()
        assert plan["status"] == "draft"
        assert plan["snapshot_id"] == dataset.snapshot.snapshot_id
        assert plan["steps"]

        second = client.post(
            "/commerce/plans",
            json=_plan_payload(project["id"], dataset.snapshot.snapshot_id),
        )
        first_page = client.get(
            "/commerce/plans",
            params={"project_id": project["id"], "snapshot_id": dataset.snapshot.snapshot_id, "limit": 1},
        )
        second_page = client.get(
            "/commerce/plans",
            params={"project_id": project["id"], "snapshot_id": dataset.snapshot.snapshot_id, "limit": 1, "offset": 1},
        )
        other_snapshot = client.get(
            "/commerce/plans",
            params={"project_id": project["id"], "snapshot_id": "different-snapshot"},
        )
        missing_scope = client.get("/commerce/plans", params={"project_id": project["id"]})
        fetched = client.get(f"/commerce/plans/{plan['id']}")
        approved = client.post(f"/commerce/plans/{plan['id']}/approve")
        repeated = client.post(f"/commerce/plans/{plan['id']}/approve")
        after_approval = client.get(
            "/commerce/plans",
            params={"project_id": project["id"], "snapshot_id": dataset.snapshot.snapshot_id},
        )

    assert second.status_code == 201
    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [second.json()["id"]]
    assert first_page.json()["next_offset"] == 1
    assert [item["id"] for item in second_page.json()["items"]] == [plan["id"]]
    assert second_page.json()["next_offset"] is None
    assert "steps" not in first_page.json()["items"][0]
    assert other_snapshot.json() == {"items": [], "next_offset": None}
    assert missing_scope.status_code == 422
    assert fetched.status_code == 200
    assert fetched.json()["id"] == plan["id"]
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "commerce_plan_not_draft"
    assert next(item for item in after_approval.json()["items"] if item["id"] == plan["id"])["status"] == "approved"


def test_benchmark_plan_practice_is_manual_append_only_and_step_scoped(tmp_path: Path) -> None:
    _write_package(tmp_path)
    dataset = import_csv_package(
        tmp_path, mode=CommerceAnalysisMode.BENCHMARK, source_type="public_dataset"
    )
    _persist_benchmark(dataset)

    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "演练项目", "stage": "operating"}
        ).json()
        plan = client.post(
            "/commerce/plans",
            json=_plan_payload(project["id"], dataset.snapshot.snapshot_id),
        ).json()
        path = f"/commerce/plans/{plan['id']}/practice"
        draft_record = client.post(
            path, json={"step_index": 0, "kind": "scenario", "note": "模拟小规模试验"}
        )
        client.post(f"/commerce/plans/{plan['id']}/approve")
        invalid_step = client.post(
            path, json={"step_index": len(plan["steps"]), "kind": "scenario", "note": "越界"}
        )
        blank_note = client.post(
            path, json={"step_index": 0, "kind": "scenario", "note": "   "}
        )
        premature_reflection = client.post(
            path, json={"step_index": 0, "kind": "reflection", "note": "没有情景的复盘"}
        )
        scenario = client.post(
            path, json={"step_index": 0, "kind": "scenario", "note": "  假设先验证一个小样本  "}
        )
        reflection = client.post(
            path, json={"step_index": 0, "kind": "reflection", "note": "仍缺少库存证据"}
        )
        first_page = client.get(path, params={"limit": 1})
        second_page = client.get(path, params={"limit": 1, "offset": 1})
        saved_plan = client.get(f"/commerce/plans/{plan['id']}")

    assert draft_record.status_code == 409
    assert draft_record.json()["detail"]["code"] == "commerce_plan_not_approved"
    assert invalid_step.status_code == 422
    assert invalid_step.json()["detail"]["code"] == "invalid_commerce_plan_step"
    assert blank_note.status_code == 422
    assert premature_reflection.status_code == 409
    assert premature_reflection.json()["detail"]["code"] == "practice_scenario_required"
    assert scenario.status_code == 201
    assert scenario.json()["note"] == "假设先验证一个小样本"
    assert scenario.json()["source_type"] == "benchmark_simulation"
    assert reflection.status_code == 201
    assert reflection.json()["kind"] == "reflection"
    assert [item["id"] for item in first_page.json()["items"]] == [reflection.json()["id"]]
    assert first_page.json()["next_offset"] == 1
    assert [item["id"] for item in second_page.json()["items"]] == [scenario.json()["id"]]
    assert second_page.json()["next_offset"] is None
    assert saved_plan.json()["status"] == "approved"


def test_commerce_talk_enforces_project_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_db() -> Generator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as owner, TestClient(app) as other:
            _register(owner, "commerce-owner@example.com")
            _register(other, "commerce-other@example.com")
            project = owner.post(
                "/projects",
                json={"name": "Owner commerce project", "stage": "operating"},
            ).json()
            response = other.post(
                "/commerce/talk",
                json=_talk_payload(project["id"], "not-relevant"),
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 404
    assert response.json()["detail"] == "project not found"
    assert not auth_is_disabled()


def test_regular_user_cannot_create_commerce_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_db() -> Generator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as first, TestClient(app) as regular:
            _register(first, "commerce-admin@example.com")
            _register(regular, "commerce-member@example.com")
            project = regular.post(
                "/projects",
                json={"name": "普通用户项目", "stage": "operating"},
            ).json()
            with testing_session() as db:
                foreign_plan = CommercePlan(
                    project_id=project["id"],
                    snapshot_id="registered-later",
                    scope_mode="benchmark",
                    question="演示隔离",
                    status="approved",
                    title="演示隔离",
                    objective="检验权限",
                    steps_json=[{"action": "模拟验证"}],
                    evidence_json=[],
                    limitations_json=[],
                )
                db.add(foreign_plan)
                db.commit()
                foreign_plan_id = foreign_plan.id
            response = regular.post(
                "/commerce/plans",
                json=_plan_payload(project["id"], "registered-later"),
            )
            regular_list = regular.get(
                "/commerce/plans",
                params={"project_id": project["id"], "snapshot_id": "registered-later"},
            )
            regular_read = regular.get("/commerce/plans/1")
            regular_practice_read = regular.get("/commerce/plans/1/practice")
            regular_practice_write = regular.post(
                "/commerce/plans/1/practice",
                json={"step_index": 0, "kind": "scenario", "note": "unauthorized"},
            )
            other_owner_list = first.get(
                "/commerce/plans",
                params={"project_id": project["id"], "snapshot_id": "registered-later"},
            )
            other_owner_practice_read = first.get(f"/commerce/plans/{foreign_plan_id}/practice")
            other_owner_practice_write = first.post(
                f"/commerce/plans/{foreign_plan_id}/practice",
                json={"step_index": 0, "kind": "scenario", "note": "cross-owner"},
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 403
    assert response.json()["detail"] == "admin access required"
    assert regular_list.status_code == 403
    assert regular_read.status_code == 403
    assert regular_practice_read.status_code == 403
    assert regular_practice_write.status_code == 403
    assert other_owner_list.status_code == 404
    assert other_owner_practice_read.status_code == 404
    assert other_owner_practice_write.status_code == 404


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "a-long-local-password"},
    )
    assert response.status_code == 201
    csrf_token = client.cookies.get("market_pilot_csrf")
    assert csrf_token
    client.headers.update({"X-CSRF-Token": csrf_token})
