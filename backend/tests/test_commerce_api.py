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
from app.db.models import Base
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

        fetched = client.get(f"/commerce/plans/{plan['id']}")
        approved = client.post(f"/commerce/plans/{plan['id']}/approve")
        repeated = client.post(f"/commerce/plans/{plan['id']}/approve")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == plan["id"]
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "commerce_plan_not_draft"


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
            response = regular.post(
                "/commerce/plans",
                json=_plan_payload(project["id"], "registered-later"),
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 403
    assert response.json()["detail"] == "admin access required"


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "a-long-local-password"},
    )
    assert response.status_code == 201
    csrf_token = client.cookies.get("market_pilot_csrf")
    assert csrf_token
    client.headers.update({"X-CSRF-Token": csrf_token})
