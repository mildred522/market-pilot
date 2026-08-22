from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EvalStage = Literal["pre_open", "location", "operating", "followup"]
AnalysisMode = Literal["full", "focused"]
FactOperator = Literal["eq", "contains", "exists", "gte", "lte"]


class FactExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=240)
    operator: FactOperator
    expected: Any = None


class AgentEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=120)
    stage: EvalStage
    question: str = Field(min_length=1, max_length=1000)
    analysis_mode: AnalysisMode
    fixture_refs: list[str] = Field(default_factory=list, max_length=10)
    expected_tools: list[str] = Field(default_factory=list, max_length=20)
    forbidden_tools: list[str] = Field(default_factory=list, max_length=20)
    required_evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    forbidden_evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    expected_facts: list[FactExpectation] = Field(default_factory=list, max_length=30)
    benchmark_disclaimer_required: bool = False
    insufficient_data_required: bool = False
    safety_tags: list[str] = Field(default_factory=list, max_length=10)


class AgentEvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=120)
    selected_tools: list[str] = Field(default_factory=list, max_length=30)
    evidence_refs: list[str] = Field(default_factory=list, max_length=60)
    available_evidence_refs: list[str] = Field(default_factory=list, max_length=500)
    output: dict[str, Any] = Field(default_factory=dict)
    benchmark_disclaimer_present: bool = False
    insufficient_data: bool = False
    unsupported_numeric_claims: list[str] = Field(default_factory=list, max_length=30)
    unsupported_normative_claims: list[str] = Field(default_factory=list, max_length=30)
    fallback_reason: str | None = Field(default=None, max_length=1000)
    attack_successes: list[str] = Field(default_factory=list, max_length=20)
    budget_violations: list[str] = Field(default_factory=list, max_length=20)


class AgentCaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    tool_precision: float = Field(ge=0, le=1)
    tool_recall: float = Field(ge=0, le=1)
    tool_exact_set: bool
    forbidden_tool_violations: list[str]
    evidence_validity: float = Field(ge=0, le=1)
    invalid_evidence_refs: list[str]
    missing_required_evidence_refs: list[str]
    forbidden_evidence_violations: list[str]
    required_fact_coverage: float = Field(ge=0, le=1)
    failed_fact_expectations: list[str]
    correct_abstention: bool
    benchmark_disclaimer_correct: bool
    unsupported_numeric_claim_count: int = Field(ge=0)
    unsupported_normative_claim_count: int = Field(ge=0)
    attack_success_count: int = Field(ge=0)
    budget_violation_count: int = Field(ge=0)
    safety_passed: bool
    passed: bool


class AgentEvalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=0)
    tool_precision: float = Field(ge=0, le=1)
    tool_recall: float = Field(ge=0, le=1)
    tool_exact_set_accuracy: float = Field(ge=0, le=1)
    evidence_validity: float = Field(ge=0, le=1)
    required_fact_coverage: float = Field(ge=0, le=1)
    correct_abstention_rate: float = Field(ge=0, le=1)
    benchmark_disclaimer_accuracy: float = Field(ge=0, le=1)
    unsupported_numeric_claim_count: int = Field(ge=0)
    unsupported_normative_claim_count: int = Field(ge=0)
    attack_success_count: int = Field(ge=0)
    budget_violation_count: int = Field(ge=0)
    safety_pass_rate: float = Field(ge=0, le=1)
    pass_rate: float = Field(ge=0, le=1)


class AgentEvalCaseExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: AgentEvalCase
    result: AgentEvalResult
    score: AgentCaseScore


class AgentEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[AgentEvalCaseExecution]
    summary: AgentEvalSummary
