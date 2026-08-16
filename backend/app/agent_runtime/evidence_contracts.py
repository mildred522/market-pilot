from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceSource = Literal[
    "current_report",
    "merchant_target",
    "benchmark",
    "project_profile",
    "metric_history",
    "external_context",
]


class EvidenceFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^E[1-9][0-9]*$")
    canonical_ref: str = Field(min_length=1, max_length=300)
    source: EvidenceSource
    label: str = Field(min_length=1, max_length=160)
    value: Any
    unit: str = Field(default="none", max_length=80)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    truncated: bool = False
    original_item_count: int | None = Field(default=None, ge=0)
    provenance: dict[str, Any] = Field(default_factory=dict)


class EvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: str = Field(min_length=8, max_length=40)
    facts: tuple[EvidenceFact, ...]
    coverage: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    omitted_fact_count: int = Field(default=0, ge=0)
    estimated_chars: int = Field(default=0, ge=0)

    def fact_for_ref(self, canonical_ref: str) -> EvidenceFact:
        for fact in self.facts:
            if fact.canonical_ref == canonical_ref:
                return fact
        raise KeyError(canonical_ref)

    def fact_for_id(self, evidence_id: str) -> EvidenceFact:
        for fact in self.facts:
            if fact.id == evidence_id:
                return fact
        raise KeyError(evidence_id)
