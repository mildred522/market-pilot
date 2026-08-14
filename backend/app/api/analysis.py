from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent_runtime.followup import ReportFollowupAgent
from app.db.models import AnalysisResult
from app.db.session import get_db
from app.schemas.analysis import AnalysisChatRequest
from app.memory.context_builder import build_conversation_context
from app.memory.history_service import MetricHistoryService
from app.memory.repository import ConversationRepository
from app.memory.project_profile import ProjectProfileService
from app.observability.agent_trace import AgentTraceRecorder

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/{analysis_id}/chat")
def chat_with_analysis(
    analysis_id: int,
    payload: AnalysisChatRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    result = db.get(AnalysisResult, analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    repository = ConversationRepository(db)
    conversation = repository.get_or_create(result.id, result.project_id)
    conversation_context = build_conversation_context(
        repository.list_recent_messages(conversation.id)
    )
    selected_memory_ids = repository.list_recent_message_ids(conversation.id)
    metrics = ProjectProfileService(db).enrich_metrics(
        result.project_id, result.metrics_json
    )
    answer = ReportFollowupAgent().answer(
        question=payload.question,
        summary=result.summary,
        metrics=metrics,
        evidence=result.evidence_json,
        actions=result.actions_json,
        risks=result.warnings_json,
        conversation_context=conversation_context,
        history_service=MetricHistoryService(
            db,
            project_id=result.project_id,
            current_analysis_id=result.id,
            current_metrics=metrics,
        ),
        selected_memory_ids=selected_memory_ids,
    )
    repository.append_exchange(
        conversation_id=conversation.id,
        question=payload.question,
        answer=answer,
    )
    trace = dict(answer.get("agent_trace", {}))
    AgentTraceRecorder(db).record(
        request_id=str(trace["request_id"]),
        project_id=result.project_id,
        operation="followup",
        run_id=None,
        analysis_id=result.id,
        initial_plan={
            "intent": "report_followup",
            "goal": "answer a grounded report follow-up",
            "tools": [
                item.get("tool")
                for item in answer.get("tool_calls", [])
                if isinstance(item, dict) and item.get("tool")
            ],
        },
        revised_plan=None,
        tool_executions=[],
        llm_calls=list(trace.get("llm_calls", [])),
        selected_memory_ids=list(trace.get("selected_memory_ids", [])),
        verification_failures=list(trace.get("verification_failures", [])),
        fallback_reasons=list(trace.get("fallback_reasons", [])),
    )
    db.commit()
    return {**answer, "conversation_id": conversation.id}


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: int, db: Session = Depends(get_db)
) -> dict[str, object]:
    result = db.get(AnalysisResult, analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    return {
        "analysis_id": result.id,
        "project_id": result.project_id,
        "stage": result.stage,
        "summary": result.summary,
        "metrics": result.metrics_json,
        "evidence": result.evidence_json,
        "actions": result.actions_json,
        "risks": result.warnings_json,
        "agent_trace": result.metrics_json.get("_agent"),
        "agent_plan": result.metrics_json.get("_agent_plan"),
    }
