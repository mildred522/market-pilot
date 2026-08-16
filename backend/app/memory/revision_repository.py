from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnswerVersion, RevisionLesson, utc_now


class AnswerVersionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        analysis_id: int,
        conversation_id: int,
        parent_version_id: int | None,
        original_question: str,
        user_feedback: str | None,
        revision_type: str,
        plan: dict[str, Any],
        answer: dict[str, Any],
    ) -> AnswerVersion:
        if parent_version_id is not None:
            parent = self.get(parent_version_id)
            if (
                parent is None
                or parent.analysis_id != analysis_id
                or parent.conversation_id != conversation_id
            ):
                raise ValueError("parent answer version does not belong to this conversation")
        version = AnswerVersion(
            analysis_id=analysis_id,
            conversation_id=conversation_id,
            parent_version_id=parent_version_id,
            original_question=original_question[:4000],
            user_feedback=user_feedback[:4000] if user_feedback else None,
            revision_type=revision_type[:48],
            plan_json=_public_dict(plan),
            execution_summary_json={
                "mode": str(answer.get("mode", "deterministic"))[:32],
                "steps": int(answer.get("steps", 0)),
                "tool_calls": _public_tool_calls(answer.get("tool_calls")),
            },
            answer=str(answer.get("answer", ""))[:8000],
            sections_json=_public_sections(answer.get("sections")),
            evidence_refs_json=_string_list(answer.get("evidence_refs")),
            quality=str(answer.get("quality", "complete"))[:32],
            validation_json=_public_dict(answer.get("claim_validation")),
        )
        self._db.add(version)
        self._db.flush()
        return version

    def get(self, version_id: int) -> AnswerVersion | None:
        return self._db.get(AnswerVersion, version_id)

    def list_for_analysis(self, analysis_id: int) -> list[AnswerVersion]:
        return list(
            self._db.scalars(
                select(AnswerVersion)
                .where(AnswerVersion.analysis_id == analysis_id)
                .order_by(AnswerVersion.created_at, AnswerVersion.id)
            ).all()
        )


class RevisionLessonRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add_candidates(
        self,
        *,
        project_id: int,
        source_version_id: int,
        candidates: list[dict[str, Any]],
    ) -> list[RevisionLesson]:
        lessons = []
        for candidate in candidates[:6]:
            lesson_type = str(candidate.get("type", ""))
            rule = candidate.get("rule")
            if lesson_type not in {
                "presentation_preference",
                "decision_constraint",
                "analysis_preference",
                "rejected_strategy",
            } or not isinstance(rule, dict) or not rule:
                continue
            status = "active" if lesson_type == "presentation_preference" else "pending"
            superseded = self._latest_conflicting_lesson(
                project_id=project_id,
                lesson_type=lesson_type,
                rule=rule,
            )
            lesson = RevisionLesson(
                project_id=project_id,
                source_version_id=source_version_id,
                scope="project",
                lesson_type=lesson_type,
                rule_json=_public_dict(rule),
                status=status,
                supersedes_id=superseded.id if superseded is not None else None,
            )
            if superseded is not None and status == "active":
                superseded.status = "superseded"
                superseded.updated_at = utc_now()
            self._db.add(lesson)
            lessons.append(lesson)
        self._db.flush()
        return lessons

    def list_active(self, project_id: int) -> list[RevisionLesson]:
        return list(
            self._db.scalars(
                select(RevisionLesson)
                .where(
                    RevisionLesson.project_id == project_id,
                    RevisionLesson.status == "active",
                )
                .order_by(RevisionLesson.id)
            ).all()
        )

    def set_status(self, lesson_id: int, status: str) -> RevisionLesson:
        if status not in {"active", "revoked", "superseded"}:
            raise ValueError("invalid revision lesson status")
        lesson = self._db.get(RevisionLesson, lesson_id)
        if lesson is None:
            raise LookupError("revision lesson not found")
        lesson.status = status
        if status == "active" and lesson.supersedes_id is not None:
            superseded = self._db.get(RevisionLesson, lesson.supersedes_id)
            if superseded is not None and superseded.status in {"active", "pending"}:
                superseded.status = "superseded"
                superseded.updated_at = utc_now()
        lesson.updated_at = utc_now()
        self._db.flush()
        return lesson

    def _latest_conflicting_lesson(
        self,
        *,
        project_id: int,
        lesson_type: str,
        rule: dict[str, Any],
    ) -> RevisionLesson | None:
        candidates = self._db.scalars(
            select(RevisionLesson)
            .where(
                RevisionLesson.project_id == project_id,
                RevisionLesson.lesson_type == lesson_type,
                RevisionLesson.status.in_(["active", "pending"]),
            )
            .order_by(RevisionLesson.id.desc())
        ).all()
        for candidate in candidates:
            shared_keys = set(candidate.rule_json).intersection(rule)
            if shared_keys and any(
                candidate.rule_json[key] != rule[key] for key in shared_keys
            ):
                return candidate
        return None


def _public_sections(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "data_findings": value.get("data_findings", [])[:8]
        if isinstance(value.get("data_findings"), list)
        else [],
        "general_advice": _string_list(value.get("general_advice")),
        "missing_information": _string_list(value.get("missing_information")),
    }


def _public_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key)[:120]: child for key, child in list(value.items())[:30]}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:20]]


def _public_tool_calls(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:8]:
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
            continue
        result.append(
            {
                "tool": item["tool"][:80],
                "arguments": _public_dict(item.get("arguments")),
            }
        )
    return result
