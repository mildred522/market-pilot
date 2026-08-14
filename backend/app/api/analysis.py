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
    )
    repository.append_exchange(
        conversation_id=conversation.id,
        question=payload.question,
        answer=answer,
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
