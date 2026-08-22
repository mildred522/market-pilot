from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import AgentExecutionTrace, AnalysisResult, Base, Project
from app.db.session import get_db
from app.main import app
from app.observability.agent_trace import AgentTraceRecorder


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(session: Session) -> tuple[AnalysisResult, AnalysisResult, str]:
    first_project = Project(name="First", stage="operating")
    second_project = Project(name="Second", stage="operating")
    session.add_all([first_project, second_project])
    session.flush()
    first_analysis = AnalysisResult(
        project_id=first_project.id,
        stage="operating",
        summary="first",
        metrics_json={},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )
    second_analysis = AnalysisResult(
        project_id=second_project.id,
        stage="operating",
        summary="second",
        metrics_json={},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )
    session.add_all([first_analysis, second_analysis])
    session.flush()
    request_id = "a6fb552f-75c2-4eb2-8805-79d0357979e6"
    AgentTraceRecorder(session).record(
        request_id=request_id,
        project_id=first_project.id,
        operation="followup",
        run_id=None,
        analysis_id=first_analysis.id,
        initial_plan={
            "intent": "report_followup",
            "goal": "answer with evidence",
            "workflow": "customer_experience",
            "dimensions": ["customer"],
            "tools": ["read_metric"],
        },
        revised_plan=None,
        tool_executions=[
            {
                "tool_name": "read_metric",
                "status": "completed",
                "duration_ms": 4,
            }
        ],
        llm_calls=[
            {
                "role": "followup",
                "provider": "test-provider",
                "model": "test-model",
                "response_format": "json_object",
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "duration_ms": 40,
                "retry_count": 1,
                "provider_request_id": "private-provider-request-id",
                "status": "completed",
            }
        ],
        selected_memory_ids=[10, 11],
        verification_failures=[],
        fallback_reasons=[],
        status="completed",
        duration_ms=52,
        evidence_events=[
            {
                "capability": "external_industry_context",
                "requirement": "required",
                "status": "completed",
                "evidence_refs": ["EXT1", "EXT2"],
                "raw_document": "must not be persisted",
            }
        ],
        budget={
            "limits": {"max_model_calls": 3, "secret_limit": 999},
            "used": {"model_calls": 1, "private_counter": 9},
            "exhausted_dimensions": [],
            "evidence_truncated": False,
            "private": "must not be public",
        },
        planning_disclosure={
            "candidate_workflow_count": 1,
            "catalog_characters": 320,
            "legacy_catalog_characters": 13643,
            "reduction_percent": 97.7,
            "private_prompt": "must not be persisted",
        },
    )
    session.commit()
    return first_analysis, second_analysis, request_id


def _client(session: Session) -> TestClient:
    def override_db() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_list_and_detail_expose_safe_aggregated_trace():
    session = _make_session()
    analysis, _, request_id = _seed(session)
    client = _client(session)
    try:
        listed = client.get(f"/analysis/{analysis.id}/agent-runs")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["usage"] == {
            "model_calls": 1,
            "tool_calls": 1,
            "replan_count": 0,
            "output_repair_count": 0,
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "token_usage_complete": True,
        }

        response = client.get(
            f"/analysis/{analysis.id}/agent-runs/{request_id}"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["duration_ms"] == 52
        assert body["selected_memory_count"] == 2
        assert body["initial_plan"]["tools"] == ["read_metric"]
        assert body["initial_plan"]["workflow"] == "customer_experience"
        assert body["initial_plan"]["dimensions"] == ["customer"]
        assert body["planning_disclosure"] == {
            "candidate_workflow_count": 1,
            "catalog_characters": 320,
            "legacy_catalog_characters": 13643,
            "reduction_percent": 97.7,
        }
        assert body["budget"]["limits"] == {"max_model_calls": 3}
        assert body["budget"]["used"] == {"model_calls": 1}
        assert any(item["stage"] == "retrieve" for item in body["timeline"])
        assert "private-provider-request-id" not in response.text
        assert "must not be persisted" not in response.text
        assert "must not be public" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_detail_is_scoped_to_the_requested_analysis():
    session = _make_session()
    first, second, request_id = _seed(session)
    client = _client(session)
    try:
        assert client.get(
            f"/analysis/{first.id}/agent-runs/{request_id}"
        ).status_code == 200
        assert client.get(
            f"/analysis/{second.id}/agent-runs/{request_id}"
        ).status_code == 404
        assert client.get("/analysis/9999/agent-runs").status_code == 404
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_missing_token_usage_remains_unknown():
    session = _make_session()
    analysis, _, request_id = _seed(session)
    trace = session.scalar(select(AgentExecutionTrace))
    assert trace is not None
    payload = dict(trace.trace_json)
    calls = [dict(item) for item in payload["llm_calls"]]
    calls[0]["total_tokens"] = None
    payload["llm_calls"] = calls
    trace.trace_json = payload
    session.commit()
    client = _client(session)
    try:
        response = client.get(
            f"/analysis/{analysis.id}/agent-runs/{request_id}"
        )
        assert response.status_code == 200
        assert response.json()["usage"]["total_tokens"] is None
        assert response.json()["usage"]["token_usage_complete"] is False
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_legacy_followup_trace_with_fallback_is_degraded():
    session = _make_session()
    analysis, _, request_id = _seed(session)
    trace = session.scalar(select(AgentExecutionTrace))
    assert trace is not None
    payload = dict(trace.trace_json)
    payload.pop("status")
    payload["fallback_reasons"] = ["planner: LLM not configured"]
    trace.trace_json = payload
    session.commit()
    client = _client(session)
    try:
        response = client.get(
            f"/analysis/{analysis.id}/agent-runs/{request_id}"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
    finally:
        app.dependency_overrides.clear()
        session.close()
