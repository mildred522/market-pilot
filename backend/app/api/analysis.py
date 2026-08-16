from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.llm_client import llm_client_from_environment
from app.agent_runtime.prompts import PROMPT_VERSION
from app.agent_runtime.revision import create_revision_plan
from app.db.models import AnalysisResult
from app.db.session import get_db
from app.external_context.followup_provider import PersistedFollowupEvidenceProvider
from app.schemas.analysis import AnalysisChatRequest
from app.memory.context_builder import build_conversation_context
from app.memory.history_service import MetricHistoryService
from app.memory.repository import ConversationRepository
from app.memory.revision_repository import (
    AnswerVersionRepository,
    RevisionLessonRepository,
)
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
    version_repository = AnswerVersionRepository(db)
    lesson_repository = RevisionLessonRepository(db)
    active_lessons = lesson_repository.list_active(result.project_id)
    conversation_context["revision_lessons"] = [
        {
            "type": lesson.lesson_type,
            "rule": lesson.rule_json,
        }
        for lesson in active_lessons
    ]
    selected_memory_ids = repository.list_recent_message_ids(conversation.id)
    metrics = ProjectProfileService(db).enrich_metrics(
        result.project_id, result.metrics_json
    )
    client = llm_client_from_environment("followup")
    parent = None
    revision_plan = None
    revision_llm_calls = []
    question = payload.question
    if payload.parent_version_id is not None:
        parent = version_repository.get(payload.parent_version_id)
        if (
            parent is None
            or parent.analysis_id != result.id
            or parent.conversation_id != conversation.id
        ):
            raise HTTPException(status_code=404, detail="answer version not found")
        question = parent.original_question
        revision_plan, revision_llm_calls = create_revision_plan(
            client=client,
            original_question=parent.original_question,
            prior_answer={
                "answer": parent.answer,
                "sections": parent.sections_json,
                "evidence_refs": parent.evidence_refs_json,
                "quality": parent.quality,
            },
            feedback=payload.feedback or "",
        )
    if question is None:
        raise HTTPException(status_code=422, detail="question is required")

    if revision_plan is not None and revision_plan.requires_confirmation:
        answer = _confirmation_required_answer(
            parent_answer=parent.answer if parent is not None else "",
            feedback=payload.feedback or "",
            llm_calls=revision_llm_calls,
            selected_memory_ids=selected_memory_ids,
        )
    else:
        answer = ReportFollowupAgent(client).answer(
            question=question,
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
            evidence_provider=PersistedFollowupEvidenceProvider(
                db,
                project_id=result.project_id,
            ),
            selected_memory_ids=selected_memory_ids,
            revision_context=(
                {
                    "plan": revision_plan.model_dump(mode="json"),
                    "feedback": payload.feedback,
                    "parent_answer": {
                        "answer": parent.answer,
                        "sections": parent.sections_json,
                        "evidence_refs": parent.evidence_refs_json,
                    },
                }
                if revision_plan is not None and parent is not None
                else None
            ),
            initial_llm_calls=revision_llm_calls,
        )
    answer.setdefault(
        "quality", "insufficient" if answer.get("mode") == "insufficient_data" else "complete"
    )
    plan_payload = (
        revision_plan.model_dump(mode="json")
        if revision_plan is not None
        else {
            "revision_type": "initial",
            "objective": "answer the report follow-up",
            "preserve_existing_evidence": True,
            "requires_confirmation": False,
            "lessons": [],
        }
    )
    version = version_repository.create(
        analysis_id=result.id,
        conversation_id=conversation.id,
        parent_version_id=parent.id if parent is not None else None,
        original_question=question,
        user_feedback=payload.feedback,
        revision_type=str(plan_payload["revision_type"]),
        plan=plan_payload,
        answer=answer,
    )
    lessons = lesson_repository.add_candidates(
        project_id=result.project_id,
        source_version_id=version.id,
        candidates=list(plan_payload.get("lessons", [])),
    )
    answer["answer_version_id"] = version.id
    answer["parent_version_id"] = version.parent_version_id
    answer["revision_plan"] = {
        key: value for key, value in plan_payload.items() if key != "lessons"
    }
    answer["memory_updates"] = [
        {
            "id": lesson.id,
            "type": lesson.lesson_type,
            "status": lesson.status,
        }
        for lesson in lessons
    ]
    repository.append_exchange(
        conversation_id=conversation.id,
        question=payload.feedback or question,
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


@router.get("/{analysis_id}/answer-versions")
def list_answer_versions(
    analysis_id: int, db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    result = db.get(AnalysisResult, analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return [
        {
            "id": version.id,
            "parent_version_id": version.parent_version_id,
            "original_question": version.original_question,
            "user_feedback": version.user_feedback,
            "revision_type": version.revision_type,
            "answer": version.answer,
            "sections": version.sections_json,
            "evidence_refs": version.evidence_refs_json,
            "quality": version.quality,
            "created_at": version.created_at,
        }
        for version in AnswerVersionRepository(db).list_for_analysis(analysis_id)
    ]


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


def _confirmation_required_answer(
    *,
    parent_answer: str,
    feedback: str,
    llm_calls: list,
    selected_memory_ids: list[int],
) -> dict[str, object]:
    request_id = str(uuid4())
    return {
        "answer": (
            "已记录这项经营事实更正，但尚未修改原始数据或重新计算指标。"
            "请确认更正后再执行重算。"
        ),
        "sections": {
            "data_findings": [],
            "general_advice": [],
            "missing_information": [f"待确认的更正：{feedback}"],
        },
        "evidence_refs": [],
        "confidence": 1.0,
        "quality": "confirmation_required",
        "mode": "confirmation_required",
        "steps": 0,
        "tool_calls": [],
        "prompt_version": PROMPT_VERSION,
        "parent_answer_preserved": bool(parent_answer),
        "llm_calls": [item.model_dump(mode="json") for item in llm_calls],
        "agent_trace": {
            "request_id": request_id,
            "llm_calls": [item.model_dump(mode="json") for item in llm_calls],
            "selected_memory_ids": selected_memory_ids,
            "verification_failures": [],
            "fallback_reasons": [],
            "replan_count": 0,
        },
    }
