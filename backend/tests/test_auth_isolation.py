from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.auth.dependencies import auth_is_disabled


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, TestClient]]:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_db() -> Generator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as first, TestClient(app) as second:
        yield first, second
    app.dependency_overrides.clear()
    engine.dispose()


def register(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "a-long-local-password"},
    )
    assert response.status_code == 201
    csrf_token = client.cookies.get("market_pilot_csrf")
    assert csrf_token
    client.headers.update({"X-CSRF-Token": csrf_token})


def pre_open_payload(project_id: int) -> dict[str, object]:
    return {
        "project_id": project_id,
        "category": "茶饮",
        "city": "成都",
        "location_type": "community",
        "area_sqm": 45,
        "seats": 16,
        "monthly_rent": 12000,
        "total_investment": 200000,
        "own_capital": 200000,
        "debt_amount": 0,
        "expected_daily_orders": 80,
        "expected_avg_order_value": 20,
        "expected_gross_margin": 0.6,
        "is_franchise": False,
        "franchise_fee": 0,
        "competitor_count": 4,
        "storefront_visibility": "medium",
    }


def test_user_cannot_read_or_analyze_another_users_project(
    clients: tuple[TestClient, TestClient],
) -> None:
    owner, other = clients
    register(owner, "owner@example.com")
    register(other, "other@example.com")
    project = owner.post(
        "/projects", json={"name": "Owner store", "stage": "pre_open"}
    ).json()
    report = owner.post("/pre-open/analyze", json=pre_open_payload(project["id"])).json()

    own_projects = owner.get("/projects")
    other_projects = other.get("/projects")
    assert own_projects.status_code == 200
    assert [item["id"] for item in own_projects.json()["items"]] == [project["id"]]
    assert other_projects.status_code == 200
    assert other_projects.json()["items"] == []
    assert other.get(f"/analysis/{report['analysis_id']}").status_code == 404
    assert other.get(f"/projects/{project['id']}/analyses").status_code == 404
    assert other.get(f"/analysis/{report['analysis_id']}/conversation").status_code == 404
    assert other.post("/pre-open/analyze", json=pre_open_payload(project["id"])).status_code == 404
    assert other.get("/dashboard/overview").json()["counts"]["projects"] == 0


def test_pre_open_report_can_continue_with_a_followup(
    clients: tuple[TestClient, TestClient],
) -> None:
    owner, _ = clients
    register(owner, "owner@example.com")
    project = owner.post(
        "/projects", json={"name": "Opening store", "stage": "pre_open"}
    ).json()
    report = owner.post("/pre-open/analyze", json=pre_open_payload(project["id"])).json()

    response = owner.post(
        f"/analysis/{report['analysis_id']}/chat",
        json={"question": "这个项目还需要验证什么？"},
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"]


def test_auth_bypass_is_ignored_outside_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("AUTH_DISABLED", "true")

    assert not auth_is_disabled()


def test_logout_revokes_the_current_session(
    clients: tuple[TestClient, TestClient],
) -> None:
    client, _ = clients
    register(client, "owner@example.com")

    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401
