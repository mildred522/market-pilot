from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.tool_contracts import (
    ToolExecutionStatus,
    ToolExecutionTrace,
)

AnalysisMode = Literal["full", "focused"]
FollowupEvidenceCapability = Literal[
    "metric_history",
    "external_industry_context",
    "location_competitors",
]
LlmRole = Literal[
    "planner",
    "replanner",
    "synthesizer",
    "followup",
    "revision_planner",
    "probe",
    "live_eval",
    "unspecified",
]

RevisionType = Literal[
    "initial",
    "rewrite_only",
    "recompose_with_existing_evidence",
    "retrieve_more_evidence",
    "recompute_metrics",
]


class LlmCallMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LlmRole
    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    response_format: Literal["json_object"] = "json_object"
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    retry_count: int = Field(default=0, ge=0)
    provider_request_id: str | None = Field(default=None, max_length=200)
    status: Literal["completed", "failed"] = "completed"
    error_code: str | None = Field(default=None, max_length=80)


class CapabilityName(StrEnum):
    PRE_OPEN_FEASIBILITY = "pre_open_feasibility"
    LOCATION_ANALYSIS = "location_analysis"
    OPERATING_DIAGNOSIS = "operating_diagnosis"


class CapabilityIntent(StrEnum):
    ASSESS_FEASIBILITY = "assess_feasibility"
    ANALYZE_LOCATION = "analyze_location"
    RECOMMEND_LOCATIONS = "recommend_locations"
    DIAGNOSE_OPERATIONS = "diagnose_operations"


class CapabilityRoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: CapabilityName
    intent: CapabilityIntent
    project_stage: Literal["pre_open", "operating"]


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


class ReplanTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Literal["recoverable_tool_failure"]
    initial_tools: list[str]
    failed_tools: list[str]
    revised_tools: list[str]
    outcome: Literal["recovered", "failed"]


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    mode: Literal["llm", "hybrid", "deterministic"]
    analysis_mode: AnalysisMode = "full"
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
    llm_calls: list[LlmCallMetadata] = Field(default_factory=list)
    replan_count: int = Field(default=0, ge=0, le=1)
    replan: ReplanTrace | None = None
    initial_plan: AgentPlan
    final_plan: AgentPlan


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


class FollowupDataClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class FollowupAnswerSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_findings: list[FollowupDataClaim] = Field(default_factory=list, max_length=8)
    general_advice: list[str] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=8)


class FollowupEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: FollowupEvidenceCapability
    purpose: str = Field(min_length=1, max_length=300)
    requirement: Literal["required", "optional"]
    success_condition: str = Field(min_length=1, max_length=300)


class RevisionLessonCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["project"] = "project"
    type: Literal[
        "presentation_preference",
        "decision_constraint",
        "analysis_preference",
        "rejected_strategy",
    ]
    rule: dict[str, str | bool | int | float] = Field(min_length=1, max_length=8)


class RevisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_type: RevisionType
    objective: str = Field(min_length=1, max_length=400)
    preserve_existing_evidence: bool = True
    requires_confirmation: bool = False
    lessons: list[RevisionLessonCandidate] = Field(default_factory=list, max_length=4)


class FollowupStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["tool", "retrieve", "answer", "insufficient_data"]
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
    evidence_requests: list[FollowupEvidenceRequest] = Field(
        default_factory=list, max_length=2
    )
    sections: FollowupAnswerSections | None = None
    confidence: float = Field(default=0, ge=0, le=1)
