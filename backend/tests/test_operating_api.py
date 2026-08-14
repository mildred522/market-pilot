from dataclasses import replace

from fastapi.testclient import TestClient

from app.agent_runtime.tools import OPERATING_TOOLS
from app.db.models import AgentExecutionTrace, AnalysisRun
from app.db.session import SessionLocal
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
        assert body["agent_trace"]["analysis_mode"] == "full"

        fetched = client.get(f"/analysis/{body['analysis_id']}").json()
        assert fetched["analysis_id"] == body["analysis_id"]
        assert fetched["stage"] == "operating"
        assert fetched["metrics"]["revenue"]["order_count"] == 8
        with SessionLocal() as db:
            trace = db.query(AgentExecutionTrace).filter_by(
                analysis_id=body["analysis_id"]
            ).one()
            assert trace.run_id == body["run_id"]
            assert trace.request_id == body["agent_trace"]["request_id"]
            assert trace.trace_json["initial_plan"]["intent"] == "operating_diagnosis"


def test_operating_persists_degraded_agent_run_status(monkeypatch):
    def fail(_context):
        raise RuntimeError("provider internals")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail),
    )

    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "降级状态测试", "stage": "operating"}
        ).json()
        body = client.post(
            "/operating/analyze-sample",
            json={"project_id": project["id"], "question": "分析经营状况"},
        ).json()

    with SessionLocal() as db:
        run = db.get(AnalysisRun, body["run_id"])
        assert run is not None
        assert body["agent_trace"]["status"] == "degraded"
        assert run.status == "degraded"


def test_operating_sample_accepts_focused_analysis_mode():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "聚焦诊断", "stage": "operating"}
        ).json()
        response = client.post(
            "/operating/analyze-sample",
            json={
                "project_id": project["id"],
                "question": "只看中差评情况",
                "analysis_mode": "focused",
            },
        )

    assert response.status_code == 200
    assert response.json()["agent_trace"]["analysis_mode"] == "focused"


def test_operating_sample_rejects_unknown_analysis_mode():
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"name": "非法模式", "stage": "operating"}
        ).json()
        response = client.post(
            "/operating/analyze-sample",
            json={
                "project_id": project["id"],
                "question": "分析经营状况",
                "analysis_mode": "automatic",
            },
        )

    assert response.status_code == 422
