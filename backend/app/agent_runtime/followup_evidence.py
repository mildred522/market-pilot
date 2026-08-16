from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.contracts import (
    FollowupEvidenceCapability,
    FollowupEvidenceRequest,
)
from app.agent_runtime.evidence_contracts import EvidenceSource
from app.agent_runtime.metric_registry import required_reference_for_question


class EvidenceMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_ref: str = Field(min_length=1, max_length=300)
    source: EvidenceSource
    label: str = Field(min_length=1, max_length=160)
    value: Any
    unit: str = Field(default="none", max_length=80)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CapabilityEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: FollowupEvidenceCapability
    status: Literal["completed", "failed"]
    facts: tuple[EvidenceMaterial, ...] = ()
    error_code: str | None = None
    message: str | None = None


class FollowupEvidenceProvider(Protocol):
    def available_capabilities(
        self, project_profile: dict[str, Any]
    ) -> set[FollowupEvidenceCapability]: ...

    def retrieve(
        self,
        capability: FollowupEvidenceCapability,
        project_profile: dict[str, Any],
    ) -> CapabilityEvidenceResult: ...


@dataclass(frozen=True)
class EvidencePolicyDecision:
    approved: tuple[FollowupEvidenceRequest, ...]
    rejected: tuple[dict[str, str], ...]


def apply_followup_evidence_policy(
    requests: Sequence[FollowupEvidenceRequest],
    *,
    question: str,
    history_available: bool,
    provider_capabilities: set[FollowupEvidenceCapability],
    attempted_capabilities: set[FollowupEvidenceCapability],
    max_requests: int = 2,
) -> EvidencePolicyDecision:
    approved: list[FollowupEvidenceRequest] = []
    rejected: list[dict[str, str]] = []
    seen: set[FollowupEvidenceCapability] = set()
    available = set(provider_capabilities)
    if history_available:
        available.add("metric_history")

    for request in requests[:max_requests]:
        capability = request.capability
        if capability in seen or capability in attempted_capabilities:
            rejected.append(_rejection(capability, "duplicate_or_already_attempted"))
            continue
        seen.add(capability)
        if capability not in available:
            rejected.append(_rejection(capability, "capability_unavailable"))
            continue
        if request.requirement == "optional" and not _explicitly_requests_context(
            question, capability
        ):
            rejected.append(_rejection(capability, "optional_retrieval_not_justified"))
            continue
        approved.append(request)
    return EvidencePolicyDecision(tuple(approved), tuple(rejected))


def execute_followup_evidence_request(
    request: FollowupEvidenceRequest,
    *,
    question: str,
    metrics: dict[str, Any],
    history_service: Any | None,
    provider: FollowupEvidenceProvider | None,
    project_profile: dict[str, Any],
) -> CapabilityEvidenceResult:
    if request.capability == "metric_history":
        if history_service is None:
            return _failure(request.capability, "capability_unavailable")
        metric_ref = required_reference_for_question(question, metrics)
        if metric_ref is None:
            return _failure(request.capability, "metric_concept_ambiguous")
        try:
            result = history_service.read(metric_ref)
        except ValueError as error:
            return _failure(request.capability, "history_unavailable", str(error))
        previous_ref = next(
            ref for ref in result["evidence_refs"] if ref.startswith("history.analysis.")
        )
        return CapabilityEvidenceResult(
            capability="metric_history",
            status="completed",
            facts=(
                EvidenceMaterial(
                    canonical_ref=previous_ref,
                    source="metric_history",
                    label=f"上一期{metric_ref}",
                    value=result["previous_value"],
                    unit=result["unit"],
                    provenance={"analysis_id": result["previous_analysis_id"]},
                ),
                EvidenceMaterial(
                    canonical_ref=f"history.comparison.{metric_ref}",
                    source="metric_history",
                    label=f"{metric_ref}历史变化",
                    value={
                        "current_value": result["current_value"],
                        "previous_value": result["previous_value"],
                        "absolute_change": result["absolute_change"],
                        "relative_change": result["relative_change"],
                    },
                    unit=result["unit"],
                    provenance={
                        "current_analysis_id": result["current_analysis_id"],
                        "previous_analysis_id": result["previous_analysis_id"],
                    },
                ),
            ),
        )
    if provider is None:
        return _failure(request.capability, "capability_unavailable")
    try:
        return provider.retrieve(request.capability, project_profile)
    except (LookupError, ValueError) as error:
        return _failure(request.capability, "evidence_unavailable", str(error))
    except Exception:
        return _failure(request.capability, "provider_failure")


def has_replan_alternative(
    *,
    attempted_capabilities: set[FollowupEvidenceCapability],
    history_available: bool,
    provider_capabilities: set[FollowupEvidenceCapability],
) -> bool:
    available = set(provider_capabilities)
    if history_available:
        available.add("metric_history")
    return bool(available - attempted_capabilities)


def _explicitly_requests_context(
    question: str, capability: FollowupEvidenceCapability
) -> bool:
    keywords = {
        "metric_history": ("上次", "上期", "之前", "历史", "相比", "变化"),
        "external_industry_context": (
            "行业",
            "市场",
            "趋势",
            "当地",
            "本地",
            "最近",
            "最新",
            "成都",
        ),
        "location_competitors": ("附近", "周边", "商圈", "竞品", "竞争对手"),
    }
    return any(keyword in question for keyword in keywords[capability])


def _rejection(
    capability: FollowupEvidenceCapability, code: str
) -> dict[str, str]:
    return {"capability": capability, "error_code": code}


def _failure(
    capability: FollowupEvidenceCapability,
    code: str,
    message: str | None = None,
) -> CapabilityEvidenceResult:
    return CapabilityEvidenceResult(
        capability=capability,
        status="failed",
        error_code=code,
        message=message,
    )
