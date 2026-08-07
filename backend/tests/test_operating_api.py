from fastapi.testclient import TestClient

from app.main import app


def test_operating_analyze_sample_returns_persisted_report():
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            json={"name": "样例面馆", "stage": "operating"},
        ).json()

        created = client.post(
            "/operating/analyze-sample",
            json={
                "project_id": project["id"],
                "question": "最近营业额下降，问题出在哪里？",
            },
        )

        assert created.status_code == 200
        body = created.json()
        assert isinstance(body["analysis_id"], int)
        assert body["stage"] == "operating"
        assert body["metrics"]["revenue"]["total_revenue"] == 336
        assert body["metrics"]["menu"]["items"]
        assert body["metrics"]["reviews"]["negative_review_count"] == 2

        fetched = client.get(f"/analysis/{body['analysis_id']}").json()
        assert fetched["analysis_id"] == body["analysis_id"]
        assert fetched["stage"] == "operating"
        assert fetched["metrics"]["revenue"]["order_count"] == 8
