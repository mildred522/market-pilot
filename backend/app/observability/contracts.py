from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal["completed", "degraded", "failed"]


class PublicPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = ""
    goal: str = ""
    workflow: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_external_api: bool = False


class AgentRunUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    output_repair_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    token_usage_complete: bool


class AgentRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    project_id: int
    analysis_id: int
    run_id: int | None
    operation: Literal["operating_analysis", "followup"]
    status: RunStatus
    created_at: datetime
    duration_ms: int = Field(ge=0)
    usage: AgentRunUsage


class AgentRunStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal[
        "plan",
        "model",
        "tool",
        "retrieve",
        "replan",
        "verify",
        "fallback",
    ]
    label: str
    status: Literal["completed", "degraded", "failed"]
    duration_ms: int | None = Field(default=None, ge=0)
    public_detail: str | None = None
    role: str | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    retry_count: int | None = Field(default=None, ge=0)
    error_code: str | None = None


class AgentRunVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_count: int = Field(ge=0)
    passed: bool


class AgentRunBudgetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limits: dict[str, int] = Field(default_factory=dict)
    used: dict[str, int] = Field(default_factory=dict)
    exhausted_dimensions: list[str] = Field(default_factory=list)
    evidence_truncated: bool = False


class AgentRunDetail(AgentRunSummary):
    initial_plan: PublicPlan
    revised_plan: PublicPlan | None = None
    timeline_order: Literal["logical"] = "logical"
    timeline: list[AgentRunStage]
    verification: AgentRunVerification
    fallback_reasons: list[str]
    selected_memory_count: int = Field(ge=0)
    budget: AgentRunBudgetView
    planning_disclosure: dict[str, int | float] = Field(default_factory=dict)
