from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisConversation, AnalysisMessage, utc_now
from app.memory.contracts import PublicMemoryMessage


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create(
        self, analysis_id: int, project_id: int
    ) -> AnalysisConversation:
        conversation = self._db.scalar(
            select(AnalysisConversation).where(
                AnalysisConversation.analysis_id == analysis_id
            )
        )
        if conversation is None:
            conversation = AnalysisConversation(
                analysis_id=analysis_id, project_id=project_id
            )
            self._db.add(conversation)
            self._db.flush()
        return conversation

    def append_exchange(
        self,
        *,
        conversation_id: int,
        question: str,
        answer: dict[str, Any],
    ) -> None:
        self._db.add(
            AnalysisMessage(
                conversation_id=conversation_id,
                role="user",
                content=question[:4000],
                mode="public",
                evidence_refs_json=[],
                tool_calls_json=[],
            )
        )
        self._db.add(
            AnalysisMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=str(answer.get("answer", ""))[:4000],
                mode=str(answer.get("mode", "deterministic"))[:32],
                evidence_refs_json=_string_list(answer.get("evidence_refs")),
                tool_calls_json=_tool_calls(answer.get("tool_calls")),
            )
        )
        conversation = self._db.get(AnalysisConversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = utc_now()

    def list_recent_messages(
        self, conversation_id: int, *, limit: int = 6
    ) -> list[PublicMemoryMessage]:
        bounded_limit = max(1, min(limit, 6))
        rows = list(
            self._db.scalars(
                select(AnalysisMessage)
                .where(AnalysisMessage.conversation_id == conversation_id)
                .order_by(AnalysisMessage.id.desc())
                .limit(bounded_limit)
            ).all()
        )
        rows.reverse()
        return [
            PublicMemoryMessage(
                role=row.role,
                content=row.content,
                mode=row.mode,
                evidence_refs=row.evidence_refs_json,
                tool_calls=row.tool_calls_json,
            )
            for row in rows
        ]

    def list_recent_message_ids(
        self, conversation_id: int, *, limit: int = 6
    ) -> list[int]:
        bounded_limit = max(1, min(limit, 6))
        values = list(
            self._db.scalars(
                select(AnalysisMessage.id)
                .where(AnalysisMessage.conversation_id == conversation_id)
                .order_by(AnalysisMessage.id.desc())
                .limit(bounded_limit)
            ).all()
        )
        values.reverse()
        return values


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:20]]


def _tool_calls(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
            continue
        arguments = item.get("arguments")
        path = arguments.get("path") if isinstance(arguments, dict) else None
        calls.append(
            {
                "tool": str(item["tool"])[:80],
                "arguments": {"path": path[:240]}
                if isinstance(path, str)
                else {},
            }
        )
    return calls
