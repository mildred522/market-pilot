from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import LlmCallMetadata
from app.db.models import AgentExecutionTrace


class StoredToolExecution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=32)
    duration_ms: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=80)
    recoverable: bool | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)


class AgentTracePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_plan: dict[str, Any]
    revised_plan: dict[str, Any] | None = None
    tool_executions: list[StoredToolExecution] = Field(default_factory=list)
    llm_calls: list[LlmCallMetadata] = Field(default_factory=list)
    selected_memory_ids: list[int] = Field(default_factory=list)
    verification_failures: list[str] = Field(default_factory=list)
    fallback_reasons: list[str] = Field(default_factory=list)


class AgentTraceRecorder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        *,
        request_id: str,
        project_id: int,
        operation: Literal["operating_analysis", "followup"],
        run_id: int | None,
        analysis_id: int | None,
        initial_plan: dict[str, Any],
        revised_plan: dict[str, Any] | None,
        tool_executions: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        selected_memory_ids: list[int],
        verification_failures: list[str],
        fallback_reasons: list[str],
    ) -> AgentExecutionTrace:
        normalized_request_id = str(UUID(request_id))
        payload = AgentTracePayload(
            initial_plan=_safe_plan(initial_plan),
            revised_plan=_safe_plan(revised_plan) if revised_plan else None,
            tool_executions=tool_executions,
            llm_calls=llm_calls,
            selected_memory_ids=selected_memory_ids,
            verification_failures=[item[:500] for item in verification_failures[:20]],
            fallback_reasons=[item[:500] for item in fallback_reasons[:20]],
        )
        row = AgentExecutionTrace(
            request_id=normalized_request_id,
            project_id=project_id,
            run_id=run_id,
            analysis_id=analysis_id,
            operation=operation,
            trace_json=payload.model_dump(mode="json"),
        )
        self._db.add(row)
        self._db.flush()
        return row


def _safe_plan(value: dict[str, Any]) -> dict[str, Any]:
    tools = value.get("tools", [])
    safe_tools = []
    if isinstance(tools, list):
        for item in tools[:8]:
            if isinstance(item, str):
                safe_tools.append(item[:80])
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                safe_tools.append(str(item["name"])[:80])
    return {
        "intent": str(value.get("intent", ""))[:80],
        "goal": str(value.get("goal", ""))[:300],
        "tools": safe_tools,
        "missing_inputs": [str(item)[:120] for item in value.get("missing_inputs", [])[:10]]
        if isinstance(value.get("missing_inputs", []), list)
        else [],
        "requires_external_api": bool(value.get("requires_external_api", False)),
    }
