from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import AgentExecutionTrace, AnalysisResult, AnalysisRun, Base, Project
from app.observability.agent_trace import AgentTraceRecorder


def make_session() -> tuple[Session, Project, AnalysisRun, AnalysisResult]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    project = Project(name="Trace project", stage="operating")
    session.add(project)
    session.flush()
    run = AnalysisRun(
        project_id=project.id,
        stage="operating",
        intent="operating_diagnosis",
        status="completed",
    )
    result = AnalysisResult(
        project_id=project.id,
        stage="operating",
        summary="summary",
        metrics_json={},
        evidence_json=[],
        actions_json=[],
        warnings_json=[],
    )
    session.add_all([run, result])
    session.flush()
    return session, project, run, result


def test_trace_recorder_persists_identifiers_and_safe_structured_fields():
    session, project, run, result = make_session()

    row = AgentTraceRecorder(session).record(
        request_id="7f291928-a596-45a8-a624-f2b0e7fa4691",
        project_id=project.id,
        operation="operating_analysis",
        run_id=run.id,
        analysis_id=result.id,
        initial_plan={"intent": "operating_diagnosis", "tools": ["analyze_revenue"]},
        revised_plan=None,
        tool_executions=[
            {"tool_name": "analyze_revenue", "status": "completed", "duration_ms": 3}
        ],
        llm_calls=[
            {
                "role": "planner",
                "provider": "test",
                "model": "small-model",
                "response_format": "json_object",
                "duration_ms": 12,
                "retry_count": 0,
            }
        ],
        selected_memory_ids=[4, 8],
        verification_failures=[],
        fallback_reasons=[],
    )
    session.commit()

    persisted = session.scalar(select(AgentExecutionTrace).where(AgentExecutionTrace.id == row.id))
    assert persisted is not None
    assert persisted.run_id == run.id
    assert persisted.analysis_id == result.id
    assert persisted.trace_json["selected_memory_ids"] == [4, 8]
    serialized = str(persisted.trace_json).lower()
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "reasoning" not in serialized


def test_trace_recorder_rejects_secret_bearing_or_unknown_fields():
    session, project, run, result = make_session()

    try:
        AgentTraceRecorder(session).record(
            request_id="7f291928-a596-45a8-a624-f2b0e7fa4691",
            project_id=project.id,
            operation="operating_analysis",
            run_id=run.id,
            analysis_id=result.id,
            initial_plan={},
            revised_plan=None,
            tool_executions=[],
            llm_calls=[],
            selected_memory_ids=[],
            verification_failures=[],
            fallback_reasons=[],
            system_prompt="must not persist",
        )
    except TypeError as error:
        assert "system_prompt" in str(error)
    else:
        raise AssertionError("secret-bearing fields must be rejected")
