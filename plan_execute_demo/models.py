from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PlanItem:
    tool: str
    reason: str


@dataclass(frozen=True)
class Plan:
    mode: str
    question: str
    items: tuple[PlanItem, ...]
    planner: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "question": self.question,
            "planner": self.planner,
            "tools": [asdict(item) for item in self.items],
        }


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: str
    metrics: dict[str, Any]
    duration_ms: int
    warning: str | None = None


@dataclass(frozen=True)
class EvidenceFact:
    id: str
    path: str
    label: str
    value: Any


@dataclass(frozen=True)
class Finding:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DemoReport:
    plan: Plan
    metrics: dict[str, Any]
    evidence: tuple[EvidenceFact, ...]
    findings: tuple[Finding, ...]
    actions: tuple[str, ...]
    trace: dict[str, Any]
    fallback_used: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.as_dict(),
            "metrics": self.metrics,
            "evidence": [asdict(item) for item in self.evidence],
            "findings": [
                {"text": item.text, "evidence_ids": list(item.evidence_ids)}
                for item in self.findings
            ],
            "actions": list(self.actions),
            "trace": self.trace,
            "fallback_used": self.fallback_used,
        }
