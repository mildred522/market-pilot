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
    )

    assert report["project_id"] == 1
    assert report["stage"] == "operating"
    assert report["intent"] == "operating_diagnosis"
    assert report["metrics"]["revenue"]["total_revenue"] == 336
    assert report["metrics"]["menu"]["items"]
    assert report["metrics"]["reviews"]["negative_review_count"] == 2
    assert report["summary"]
    assert report["evidence"]
    assert report["actions"]
