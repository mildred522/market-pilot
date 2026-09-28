from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, get_current_user, require_owned_analysis
from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.llm_client import llm_client_from_environment
from app.agent_runtime.prompts import PROMPT_VERSION
from app.agent_runtime.revision import create_revision_plan
from app.corrections.repository import (
    AnalysisInputSnapshotRepository,
    CorrectionProposalRepository,
)
from app.db.models import AnalysisResult
from app.db.session import get_db
from app.external_context.followup_provider import PersistedFollowupEvidenceProvider
from app.knowledge.factory import build_knowledge_retrieval_service
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
from app.services.runtime_config import runtime_config

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/{analysis_id}/chat")
def chat_with_analysis(
    analysis_id: int,
    payload: AnalysisChatRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    result = require_owned_analysis(db, current_user, analysis_id)
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
            has_explicit_correction=bool(revision_plan.corrections),
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
                knowledge_service=build_knowledge_retrieval_service(
                    db, runtime_config.knowledge_rag_settings()
                ),
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
    proposals = []
    if revision_plan is not None and revision_plan.requires_confirmation:
        snapshot = AnalysisInputSnapshotRepository(db).get_for_analysis(result.id)
        if snapshot is not None:
            proposal_repository = CorrectionProposalRepository(db)
            for candidate in revision_plan.corrections:
                old_value = snapshot.cost_assumptions_json.get(candidate.field)
                if (
                    isinstance(old_value, (int, float))
                    and not isinstance(old_value, bool)
                    and float(old_value) != candidate.new_value
                ):
                    proposals.append(
                        proposal_repository.create(
                            project_id=result.project_id,
                            source_analysis_id=result.id,
                            source_answer_version_id=version.id,
                            target_field=candidate.field,
                            old_value=float(old_value),
                            new_value=candidate.new_value,
                            reason=candidate.reason,
                        )
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
    answer["correction_proposals"] = [
        {
            "id": proposal.id,
            "field": proposal.target_field,
            "old_value": proposal.old_value,
            "new_value": proposal.new_value,
            "status": proposal.status,
            "idempotency_key": proposal.idempotency_key,
        }
        for proposal in proposals
    ]
    repository.append_exchange(
        conversation_id=conversation.id,
        question=payload.feedback or question,
        answer=answer,
        answer_version_id=version.id,
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
        status=str(trace.get("status", "completed")),
        duration_ms=int(trace.get("duration_ms", 0)),
        replan_count=int(trace.get("replan_count", 0)),
        output_repair_count=int(trace.get("output_repair_count", 0)),
        evidence_events=list(trace.get("evidence_events", [])),
        budget=dict(trace.get("budget", {})),
        planning_disclosure=dict(trace.get("planning_disclosure", {})),
    )
    db.commit()
    return {**answer, "conversation_id": conversation.id}


@router.get("/{analysis_id}/answer-versions")
def list_answer_versions(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    require_owned_analysis(db, current_user, analysis_id)
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


@router.get("/{analysis_id}/conversation")
def get_conversation_history(
    analysis_id: int,
    limit: int = Query(default=40, ge=1, le=100),
    before_message_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    """Return persisted conversation data only; this route never invokes an agent."""
    require_owned_analysis(db, current_user, analysis_id)
    repository = ConversationRepository(db)
    conversation = repository.get_for_analysis(analysis_id)
    if conversation is None:
        return {
            "conversation_id": None,
            "items": [],
            "next_before_message_id": None,
        }
    messages = repository.list_messages(
        conversation.id, limit=limit, before_id=before_message_id
    )
    return {
        "conversation_id": conversation.id,
        "items": [
            {
                "id": message.id,
                "role": message.role,
                "status": message.status,
                "content": message.content,
                "mode": message.mode,
                "answer_version_id": message.answer_version_id,
                "evidence_refs": message.evidence_refs_json,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "next_before_message_id": (
            messages[0].id if len(messages) == limit else None
        ),
    }


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    result = require_owned_analysis(db, current_user, analysis_id)

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
    has_explicit_correction: bool,
    llm_calls: list,
    selected_memory_ids: list[int],
) -> dict[str, object]:
    request_id = str(uuid4())
    if has_explicit_correction:
        answer_text = (
            "已生成经营事实更正单，尚未修改原始数据或重新计算指标。"
            "请核对新旧值后确认或拒绝。"
        )
        mode = "confirmation_required"
        quality = "confirmation_required"
        missing_information = [f"待确认的更正：{feedback}"]
    else:
        answer_text = (
            "识别到经营事实更正意图，但没有找到可确认的明确字段和新值。"
            "请说明要修改的经营假设及具体数值。"
        )
        mode = "insufficient_data"
        quality = "insufficient"
        missing_information = [f"缺少明确的新值：{feedback}"]
    return {
        "answer": answer_text,
        "sections": {
            "data_findings": [],
            "general_advice": [],
            "missing_information": missing_information,
        },
        "evidence_refs": [],
        "confidence": 1.0,
        "quality": quality,
        "mode": mode,
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
