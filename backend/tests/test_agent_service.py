from pathlib import Path

import pandas as pd

from app.services.agent_service import AgentService

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def test_agent_service_returns_operating_diagnosis_report():
    service = AgentService()
    orders = pd.read_csv(SAMPLE_DIR / "orders.csv")
    menu = pd.read_csv(SAMPLE_DIR / "menu_items.csv")
    reviews = pd.read_csv(SAMPLE_DIR / "reviews.csv")

    report = service.analyze_operating(
        project_id=1,
        question="最近营业额下降，问题出在哪里？",
        orders=orders,
        menu=menu,
        reviews=reviews,
        cost_assumptions={
            "monthly_rent": 18000,
            "monthly_labor": 24000,
            "monthly_utilities": 3000,
            "monthly_marketing": 2000,
            "other_fixed_costs": 3000,
            "cash_balance": 120000,
            "delivery_commission_rate": 0.2,
            "delivery_packaging_per_order": 1.5,
        },
    )

    assert report["project_id"] == 1
    assert report["stage"] == "operating"
    assert report["intent"] == "operating_diagnosis"
    assert report["metrics"]["revenue"]["total_revenue"] == 336
    assert report["metrics"]["menu"]["items"]
    assert report["metrics"]["reviews"]["negative_review_count"] == 2
    assert report["metrics"]["survival"]["risk_level"] == "high"
    assert report["metrics"]["channels"]["delivery_contribution_profit"] == 41.1
    assert report["metrics"]["time_patterns"]["peak_daypart"] == "lunch"
    assert report["metrics"]["discounts"]["discounted_order_count"] == 0
    assert "日保本营业额" in report["summary"]
    assert any("现金预计" in warning for warning in report["warnings"])
    assert any("外卖营收" in evidence for evidence in report["evidence"])
    assert any("营收最高时段" in evidence for evidence in report["evidence"])
    assert report["summary"]
    assert report["evidence"]
    assert report["actions"]
