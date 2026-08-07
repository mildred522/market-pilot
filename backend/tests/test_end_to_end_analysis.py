from fastapi.testclient import TestClient

from app.main import app


def test_demo_flow_creates_pre_open_and_operating_reports():
    with TestClient(app) as client:
        pre_project = client.post(
            "/projects",
            json={"name": "加盟奶茶店演示", "stage": "pre_open"},
        ).json()
        pre_report = client.post(
            "/pre-open/analyze",
            json={
                "project_id": pre_project["id"],
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

        operating_project = client.post(
            "/projects",
            json={"name": "面馆经营诊断演示", "stage": "operating"},
        ).json()
        operating_report = client.post(
            "/operating/analyze-sample",
            json={
                "project_id": operating_project["id"],
                "question": "最近营业额下降，问题出在哪里？",
            },
        ).json()

        fetched_pre = client.get(f"/analysis/{pre_report['analysis_id']}").json()
        fetched_operating = client.get(
            f"/analysis/{operating_report['analysis_id']}"
        ).json()

        assert fetched_pre["stage"] == "pre_open"
        assert fetched_pre["metrics"]["estimated_daily_revenue"] == 2160
        assert fetched_pre["risks"]
        assert fetched_pre["actions"]
        assert fetched_operating["stage"] == "operating"
        assert fetched_operating["metrics"]["revenue"]["total_revenue"] == 336
        assert fetched_operating["metrics"]["menu"]["items"]
        assert fetched_operating["metrics"]["reviews"]["negative_review_count"] == 2
