from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ProjectProfile
from app.db.session import SessionLocal
from app.main import app


def test_create_project_returns_project_id():
    with TestClient(app) as client:
        response = client.post(
            "/projects",
            json={"name": "加盟奶茶店评估", "stage": "pre_open"},
        )

        assert response.status_code == 201
        body = response.json()
        assert isinstance(body["id"], int)
        assert body["name"] == "加盟奶茶店评估"
        assert body["stage"] == "pre_open"


def test_pre_open_analyze_returns_basic_risk_report():
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "社区粉面店", "stage": "pre_open"},
        ).json()

        response = client.post(
            "/pre-open/analyze",
            json={
                "project_id": project["id"],
                "category": "粉面",
                "city": "成都",
                "location_type": "community",
                "area_sqm": 60,
                "seats": 28,
                "monthly_rent": 18000,
                "total_investment": 280000,
                "own_capital": 150000,
                "debt_amount": 130000,
                "expected_daily_orders": 90,
                "expected_avg_order_value": 24,
                "expected_gross_margin": 0.62,
                "is_franchise": True,
                "franchise_fee": 68000,
                "competitor_count": 8,
                "storefront_visibility": "medium",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["stage"] == "pre_open"
        assert body["project_id"] == project["id"]
        assert isinstance(body["analysis_id"], int)
        assert body["summary"]
        assert body["metrics"]["estimated_daily_revenue"] == 2160
        assert body["metrics"]["estimated_daily_gross_profit"] == 1339.2
        assert "risks" in body
        assert "actions" in body
        with SessionLocal() as db:
            profile = db.scalar(
                select(ProjectProfile).where(
                    ProjectProfile.project_id == project["id"]
                )
            )
            assert profile is not None
            assert profile.city == "成都"
            assert profile.category == "粉面"
            assert profile.store_identity == "社区粉面店"


def test_get_analysis_returns_persisted_pre_open_report():
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "加盟奶茶店", "stage": "pre_open"},
        ).json()
        created = client.post(
            "/pre-open/analyze",
            json={
                "project_id": project["id"],
                "category": "茶饮",
                "city": "杭州",
                "location_type": "mall",
                "area_sqm": 45,
                "seats": 16,
                "monthly_rent": 26000,
                "total_investment": 420000,
                "own_capital": 180000,
                "debt_amount": 240000,
                "expected_daily_orders": 120,
                "expected_avg_order_value": 18,
                "expected_gross_margin": 0.58,
                "is_franchise": True,
                "franchise_fee": 120000,
                "competitor_count": 12,
                "storefront_visibility": "high",
            },
        ).json()

        response = client.get(f"/analysis/{created['analysis_id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["analysis_id"] == created["analysis_id"]
        assert body["project_id"] == project["id"]
        assert body["stage"] == "pre_open"
        assert body["summary"]
        assert body["metrics"]["estimated_daily_revenue"] == 2160
        assert body["risks"]
        assert body["actions"]
