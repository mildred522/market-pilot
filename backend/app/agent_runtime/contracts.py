from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=500)
    kind: Literal["observed", "inferred", "assumption", "unknown"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=500)
    metric: str | None = Field(default=None, max_length=120)
    target: str | None = Field(default=None, max_length=120)
    deadline_days: int | None = Field(default=None, ge=1, le=365)


class AgentSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)
    findings: list[AgentFinding] = Field(min_length=1, max_length=8)
    actions: list[AgentAction] = Field(min_length=1, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


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
