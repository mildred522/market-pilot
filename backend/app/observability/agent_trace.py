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

    status: Literal["completed", "degraded", "failed"] = "completed"
    duration_ms: int = Field(default=0, ge=0)
    initial_plan: dict[str, Any]
    revised_plan: dict[str, Any] | None = None
    tool_executions: list[StoredToolExecution] = Field(default_factory=list)
    llm_calls: list[LlmCallMetadata] = Field(default_factory=list)
    selected_memory_ids: list[int] = Field(default_factory=list)
    verification_failures: list[str] = Field(default_factory=list)
    fallback_reasons: list[str] = Field(default_factory=list)
    replan_count: int = Field(default=0, ge=0, le=1)
    output_repair_count: int = Field(default=0, ge=0, le=1)
    evidence_events: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    budget: dict[str, Any] = Field(default_factory=dict)
    planning_disclosure: dict[str, int | float] = Field(default_factory=dict)


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
        status: Literal["completed", "degraded", "failed"] = "completed",
        duration_ms: int = 0,
        replan_count: int = 0,
        output_repair_count: int = 0,
        evidence_events: list[dict[str, Any]] | None = None,
        budget: dict[str, Any] | None = None,
        planning_disclosure: dict[str, Any] | None = None,
    ) -> AgentExecutionTrace:
        normalized_request_id = str(UUID(request_id))
        payload = AgentTracePayload(
            status=status,
            duration_ms=duration_ms,
            initial_plan=_safe_plan(initial_plan),
            revised_plan=_safe_plan(revised_plan) if revised_plan else None,
            tool_executions=tool_executions,
            llm_calls=llm_calls,
            selected_memory_ids=selected_memory_ids,
            verification_failures=[item[:500] for item in verification_failures[:20]],
            fallback_reasons=[item[:500] for item in fallback_reasons[:20]],
            replan_count=replan_count,
            output_repair_count=output_repair_count,
            evidence_events=_safe_evidence_events(evidence_events or []),
            budget=_safe_budget(budget or {}),
            planning_disclosure=_safe_planning_disclosure(
                planning_disclosure or {}
            ),
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
        "workflow": str(value.get("workflow", ""))[:80] or None,
        "dimensions": [
            str(item)[:80] for item in value.get("dimensions", [])[:6]
        ]
        if isinstance(value.get("dimensions", []), list)
        else [],
        "tools": safe_tools,
        "missing_inputs": [str(item)[:120] for item in value.get("missing_inputs", [])[:10]]
        if isinstance(value.get("missing_inputs", []), list)
        else [],
        "requires_external_api": bool(value.get("requires_external_api", False)),
    }


def _safe_planning_disclosure(value: dict[str, Any]) -> dict[str, int | float]:
    safe: dict[str, int | float] = {}
    for key in (
        "candidate_workflow_count",
        "catalog_characters",
        "legacy_catalog_characters",
        "reduction_percent",
    ):
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            safe[key] = max(0, item)
    return safe


def _safe_evidence_events(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_events = []
    for value in values[:10]:
        safe_events.append(
            {
                "capability": str(value.get("capability", ""))[:80],
                "requirement": str(value.get("requirement", ""))[:24],
                "status": str(value.get("status", ""))[:24],
                "evidence_count": len(value.get("evidence_refs", []))
                if isinstance(value.get("evidence_refs"), list)
                else 0,
                "error_code": str((value.get("error") or {}).get("code", ""))[:80]
                if isinstance(value.get("error"), dict)
                else None,
            }
        )
    return safe_events


def _safe_budget(value: dict[str, Any]) -> dict[str, Any]:
    limits = value.get("limits") if isinstance(value.get("limits"), dict) else {}
    used = value.get("used") if isinstance(value.get("used"), dict) else {}
    integer_limit_keys = (
        "max_model_calls",
        "max_replans",
        "max_repairs",
        "max_external_retrievals",
        "max_evidence_characters",
        "run_timeout_ms",
    )
    integer_used_keys = (
        "model_calls",
        "replans",
        "repairs",
        "external_retrievals",
        "elapsed_ms",
    )
    return {
        "limits": {
            key: max(0, int(limits[key]))
            for key in integer_limit_keys
            if isinstance(limits.get(key), (int, float))
        },
        "used": {
            key: max(0, int(used[key]))
            for key in integer_used_keys
            if isinstance(used.get(key), (int, float))
        },
        "exhausted_dimensions": [
            str(item)[:80]
            for item in value.get("exhausted_dimensions", [])[:6]
        ]
        if isinstance(value.get("exhausted_dimensions"), list)
        else [],
        "evidence_truncated": bool(value.get("evidence_truncated", False)),
    }
