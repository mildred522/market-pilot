from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ProjectProfile
from app.db.session import SessionLocal
from app.main import app


ORDERS = """订单号,下单时间,渠道,菜品名称,数量,实收金额
O1,2026-08-01 12:00,堂食,牛肉面,2,56
O2,2026-08-02 18:00,外卖,拌面,1,26
"""
MENU = """菜品名称,菜品分类,售价,单位成本
牛肉面,粉面,28,10
拌面,粉面,26,8
"""
REVIEWS = """评论时间,评分,评论内容,渠道
2026-08-01 13:00,5,味道不错,堂食
2026-08-02 20:00,2,配送太慢,外卖
"""


def _upload(client: TestClient, project_id: int, file_type: str, content: str):
    return client.post(
        "/files/upload",
        data={"project_id": project_id, "file_type": file_type},
        files={"file": (f"../{file_type}.csv", content.encode("utf-8"), "text/csv")},
    )


def test_uploaded_chinese_csv_files_generate_real_operating_report():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "真实上传诊断", "stage": "operating"}
        ).json()
        uploaded = {
            file_type: _upload(client, project["id"], file_type, content).json()
            for file_type, content in {
                "orders": ORDERS,
                "menu_items": MENU,
                "reviews": REVIEWS,
            }.items()
        }

        response = client.post(
            "/operating/analyze",
            json={
                "project_id": project["id"],
                "question": "分析订单、菜品和差评，为什么经营不赚钱？",
                "cost_assumptions": {
                    "monthly_rent": 18000.0,
                    "monthly_labor": 24000.0,
                    "monthly_utilities": 3000.0,
                    "monthly_marketing": 2000.0,
                    "other_fixed_costs": 3000.0,
                    "cash_balance": 120000.0,
                    "delivery_commission_rate": 0.2,
                    "delivery_packaging_per_order": 1.5,
                },
                **{
                    file_type: {
                        "file_id": item["file_id"],
                        "mapping": item["suggested_mapping"],
                    }
                    for file_type, item in uploaded.items()
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["revenue"]["total_revenue"] == 82
    assert body["metrics"]["revenue"]["order_count"] == 2
    assert body["metrics"]["menu"]["items"]
    assert body["metrics"]["reviews"]["negative_review_count"] == 1
    assert body["metrics"]["survival"]["monthly_fixed_cost"] == 50000
    assert body["metrics"]["survival"]["risk_level"] == "high"
    assert body["metrics"]["channels"]["delivery_contribution_profit"] == 11.3
    assert all(Path(item["filename"]).name == item["filename"] for item in uploaded.values())
    assert all(item["missing_columns"] == [] for item in uploaded.values())
    with SessionLocal() as db:
        profile = db.scalar(
            select(ProjectProfile).where(ProjectProfile.project_id == project["id"])
        )
        assert profile is not None
        assert profile.cost_assumptions_json["monthly_rent"] == 18000.0
        assert profile.sources_json["cost_assumptions"] == "user_input"


def test_operating_analysis_rejects_incomplete_mapping():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "映射错误", "stage": "operating"}
        ).json()
        order_upload = _upload(client, project["id"], "orders", ORDERS).json()
        menu_upload = _upload(client, project["id"], "menu_items", MENU).json()
        review_upload = _upload(client, project["id"], "reviews", REVIEWS).json()
        order_upload["suggested_mapping"].pop("actual_amount")

        response = client.post(
            "/operating/analyze",
            json={
                "project_id": project["id"],
                "question": "经营诊断",
                "cost_assumptions": {
                    "monthly_rent": 18000.0,
                    "monthly_labor": 24000.0,
                    "monthly_utilities": 3000.0,
                },
                "orders": {"file_id": order_upload["file_id"], "mapping": order_upload["suggested_mapping"]},
                "menu_items": {"file_id": menu_upload["file_id"], "mapping": menu_upload["suggested_mapping"]},
                "reviews": {"file_id": review_upload["file_id"], "mapping": review_upload["suggested_mapping"]},
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_columns"
