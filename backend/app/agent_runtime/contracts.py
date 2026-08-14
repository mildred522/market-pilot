from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.tool_contracts import (
    ToolExecutionStatus,
    ToolExecutionTrace,
)


class PlannedTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=300)


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=300)
    tools: list[PlannedTool] = Field(max_length=8)
    missing_inputs: list[str] = Field(default_factory=list, max_length=10)
    requires_external_api: bool = False


class SynthesisFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=6)


class CompactAgentSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=800)
    findings: list[SynthesisFinding] = Field(min_length=1, max_length=4)
    actions: list[str] = Field(min_length=1, max_length=4)
    warnings: list[str] = Field(default_factory=list, max_length=4)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["llm", "hybrid", "deterministic"]
    provider: str
    model: str | None = None
    prompt_version: str
    selected_tools: list[str]
    planning_used_llm: bool
    synthesis_used_llm: bool
    fallback_reasons: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)
    status: ToolExecutionStatus = "completed"
    tool_executions: list[ToolExecutionTrace] = Field(default_factory=list)


class FollowupToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(
        default=None,
        max_length=240,
        description="Canonical metrics.section.field path for read_metric.",
    )
    field: str | None = Field(
        default=None, max_length=240, description="Compatible alias for path."
    )
    metric: str | None = Field(
        default=None, max_length=240, description="Compatible alias for path."
    )
    reference: str | None = Field(
        default=None, max_length=240, description="Compatible alias for path."
    )


class FollowupStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["tool", "answer", "insufficient_data"]
    tool_name: str | None = Field(default=None, max_length=80)
    arguments: FollowupToolArguments = Field(
        default_factory=FollowupToolArguments,
        description=(
            'For read_metric use {"path":"metrics.section.field"}. '
            "Other read-only tools use an empty object."
        ),
    )
    answer: str | None = Field(default=None, max_length=1600)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0, ge=0, le=1)
