from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.agent_runtime.evidence_contracts import EvidenceFact, EvidencePack, EvidenceSource
from app.agent_runtime.followup_evidence import EvidenceMaterial
from app.agent_runtime.metric_registry import definition_for


@dataclass(frozen=True)
class _Candidate:
    canonical_ref: str
    source: EvidenceSource
    label: str
    value: Any
    unit: str = "none"
    limitations: tuple[str, ...] = ()
    truncated: bool = False
    original_item_count: int | None = None


def build_evidence_pack(
    *,
    metrics: dict[str, Any],
    summary: str,
    evidence: list[str],
    actions: list[str],
    risks: list[str],
    max_chars: int = 24_000,
    max_facts: int = 200,
    max_array_items: int = 20,
) -> EvidencePack:
    if max_chars < 1 or max_facts < 1 or max_array_items < 1:
        raise ValueError("evidence pack limits must be positive")

    candidates = _metric_candidates(metrics, max_array_items)
    candidates.extend(_reference_candidates(metrics, max_array_items))
    candidates.extend(_profile_candidates(metrics, max_array_items))
    candidates.extend(_report_candidates(summary, evidence, actions, risks))
    candidates.sort(key=lambda item: item.canonical_ref)

    selected: list[_Candidate] = []
    estimated_chars = 0
    omitted = 0
    for candidate in candidates:
        if len(selected) >= max_facts:
            omitted += 1
            continue
        candidate_chars = len(
            json.dumps(candidate.__dict__, ensure_ascii=False, default=str)
        )
        if estimated_chars + candidate_chars > max_chars:
            omitted += 1
            continue
        selected.append(candidate)
        estimated_chars += candidate_chars

    facts = tuple(
        EvidenceFact(id=f"E{index}", **candidate.__dict__)
        for index, candidate in enumerate(selected, start=1)
    )
    fingerprint = json.dumps(
        [fact.model_dump(exclude={"id"}) for fact in facts],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    pack_id = "ep-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return EvidencePack(
        pack_id=pack_id,
        facts=facts,
        coverage=_coverage(metrics),
        truncated=omitted > 0 or any(fact.truncated for fact in facts),
        omitted_fact_count=omitted,
        estimated_chars=estimated_chars,
    )


def extend_evidence_pack(
    evidence_pack: EvidencePack, materials: list[EvidenceMaterial]
) -> EvidencePack:
    existing_refs = {fact.canonical_ref for fact in evidence_pack.facts}
    additions = [
        material
        for material in materials
        if material.canonical_ref not in existing_refs
    ]
    next_id = len(evidence_pack.facts) + 1
    added_facts = tuple(
        EvidenceFact(
            id=f"E{next_id + index}",
            canonical_ref=material.canonical_ref,
            source=material.source,
            label=material.label,
            value=material.value,
            unit=material.unit,
            limitations=material.limitations,
            provenance=material.provenance,
        )
        for index, material in enumerate(additions)
    )
    facts = (*evidence_pack.facts, *added_facts)
    fingerprint = json.dumps(
        [fact.model_dump(exclude={"id"}) for fact in facts],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    extra_chars = sum(
        len(json.dumps(item.model_dump(), ensure_ascii=False, default=str))
        for item in additions
    )
    return EvidencePack(
        pack_id="ep-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16],
        facts=facts,
        coverage=evidence_pack.coverage,
        truncated=evidence_pack.truncated,
        omitted_fact_count=evidence_pack.omitted_fact_count,
        estimated_chars=evidence_pack.estimated_chars + extra_chars,
    )


def _metric_candidates(
    metrics: dict[str, Any], max_array_items: int
) -> list[_Candidate]:
    result: list[_Candidate] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                if not str(key).startswith("_"):
                    visit(value[key], f"{path}.{key}")
            return
        compacted, truncated, count = _compact(value, max_array_items)
        definition = definition_for(path)
        result.append(
            _Candidate(
                canonical_ref=path,
                source="current_report",
                label=definition.label if definition else path,
                value=compacted,
                unit=definition.unit if definition else "none",
                limitations=definition.limitations if definition else (),
                truncated=truncated,
                original_item_count=count,
            )
        )

    for section in sorted(metrics):
        if not section.startswith("_"):
            visit(metrics[section], f"metrics.{section}")
    return result


def _reference_candidates(
    metrics: dict[str, Any], max_array_items: int
) -> list[_Candidate]:
    result: list[_Candidate] = []
    for key, source, prefix, suffix in (
        ("_targets", "merchant_target", "targets.", "商户目标"),
        ("_benchmarks", "benchmark", "benchmarks.", "参考基准"),
    ):
        values = metrics.get(key)
        if not isinstance(values, dict):
            continue
        for metric_ref in sorted(values):
            value, truncated, count = _compact(values[metric_ref], max_array_items)
            definition = definition_for(metric_ref)
            result.append(
                _Candidate(
                    canonical_ref=f"{prefix}{metric_ref}",
                    source=source,
                    label=f"{definition.label if definition else metric_ref}{suffix}",
                    value=value,
                    unit=definition.unit if definition else "none",
                    truncated=truncated,
                    original_item_count=count,
                )
            )
    return result


def _profile_candidates(
    metrics: dict[str, Any], max_array_items: int
) -> list[_Candidate]:
    profile = metrics.get("_project_profile")
    if not isinstance(profile, dict):
        return []
    public = {
        key: profile[key]
        for key in ("store_identity", "current_stage", "city", "category", "preferences")
        if profile.get(key) not in (None, "", {})
    }
    result: list[_Candidate] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                if not str(key).startswith("_"):
                    visit(value[key], f"{path}.{key}")
            return
        compacted, truncated, count = _compact(value, max_array_items)
        result.append(
            _Candidate(
                canonical_ref=path,
                source="project_profile",
                label=path.removeprefix("project_profile."),
                value=compacted,
                truncated=truncated,
                original_item_count=count,
            )
        )

    visit(public, "project_profile")
    return result


def _report_candidates(
    summary: str,
    evidence: list[str],
    actions: list[str],
    risks: list[str],
) -> list[_Candidate]:
    result = [
        _Candidate("report.summary", "current_report", "报告摘要", summary)
    ]
    for collection, values, label in (
        ("evidence", evidence, "报告证据"),
        ("actions", actions, "行动建议"),
        ("risks", risks, "风险提示"),
    ):
        result.extend(
            _Candidate(
                f"report.{collection}.{index}",
                "current_report",
                f"{label}{index + 1}",
                value,
            )
            for index, value in enumerate(values)
        )
    return result


def _compact(value: Any, max_array_items: int) -> tuple[Any, bool, int | None]:
    if isinstance(value, list):
        compacted = [_sanitize(item, max_array_items) for item in value[:max_array_items]]
        return compacted, len(value) > max_array_items, len(value)
    return _sanitize(value, max_array_items), False, None


def _sanitize(value: Any, max_array_items: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(child, max_array_items)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_sanitize(item, max_array_items) for item in value[:max_array_items]]
    return value


def _coverage(metrics: dict[str, Any]) -> dict[str, Any]:
    revenue = metrics.get("revenue") if isinstance(metrics.get("revenue"), dict) else {}
    reviews = metrics.get("reviews") if isinstance(metrics.get("reviews"), dict) else {}
    time_patterns = (
        metrics.get("time_patterns")
        if isinstance(metrics.get("time_patterns"), dict)
        else {}
    )
    daily = revenue.get("daily_revenue")
    daily_rows = daily if isinstance(daily, list) else []
    return {
        "date_start": daily_rows[0].get("date")
        if daily_rows and isinstance(daily_rows[0], dict)
        else None,
        "date_end": daily_rows[-1].get("date")
        if daily_rows and isinstance(daily_rows[-1], dict)
        else None,
        "order_count": revenue.get("order_count"),
        "review_count": reviews.get("review_count"),
        "observed_days": time_patterns.get("observed_days"),
    }
