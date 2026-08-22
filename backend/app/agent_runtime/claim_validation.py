from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agent_runtime.contracts import FollowupAnswerSections
from app.agent_runtime.evidence_contracts import EvidencePack


_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"
)


@dataclass(frozen=True)
class ValidatedClaim:
    text: str
    evidence_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class InvalidClaim:
    text: str
    evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ClaimValidationResult:
    valid_claims: tuple[ValidatedClaim, ...]
    invalid_claims: tuple[InvalidClaim, ...]
    general_advice: tuple[str, ...]
    missing_information: tuple[str, ...]

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for claim in self.valid_claims:
            for reference in claim.evidence_refs:
                seen.setdefault(reference, None)
        return tuple(seen)


def validate_answer_sections(
    sections: FollowupAnswerSections, evidence_pack: EvidencePack
) -> ClaimValidationResult:
    valid: list[ValidatedClaim] = []
    invalid: list[InvalidClaim] = []
    for claim in sections.data_findings:
        facts = []
        unknown_id = None
        for evidence_id in claim.evidence_ids:
            try:
                facts.append(evidence_pack.fact_for_id(evidence_id))
            except KeyError:
                unknown_id = evidence_id
                break
        if unknown_id:
            invalid.append(
                InvalidClaim(
                    claim.text,
                    tuple(claim.evidence_ids),
                    f"unknown_evidence_id:{unknown_id}",
                )
            )
            continue

        unsupported = unsupported_number(
            claim.text, [fact.value for fact in facts]
        )
        if unsupported:
            invalid.append(
                InvalidClaim(
                    claim.text,
                    tuple(claim.evidence_ids),
                    f"unsupported_number:{unsupported.rstrip('%')}",
                )
            )
            continue
        valid.append(
            ValidatedClaim(
                claim.text,
                tuple(claim.evidence_ids),
                tuple(fact.canonical_ref for fact in facts),
            )
        )
    return ClaimValidationResult(
        valid_claims=tuple(valid),
        invalid_claims=tuple(invalid),
        general_advice=tuple(sections.general_advice),
        missing_information=tuple(sections.missing_information),
    )


def unsupported_number(text: str, evidence_values: list[Any]) -> str | None:
    """Return the first numeric token that is not grounded in cited evidence."""
    allowed_values: list[float] = []
    for value in evidence_values:
        allowed_values.extend(_numeric_values(value))
    allowed_values.extend(_derived_numeric_values(allowed_values))
    return next(
        (
            token
            for token in _number_tokens(text)
            if not _matches_evidence(token, allowed_values)
        ),
        None,
    )


def _derived_numeric_values(values: list[float]) -> list[float]:
    """Allow transparent two-value comparisons without accepting free arithmetic."""
    if not 2 <= len(values) <= 12:
        return []
    derived: list[float] = []
    for left in values:
        for right in values:
            if left == right:
                continue
            derived.extend((left + right, left - right, abs(left - right)))
            if right:
                derived.extend((left / right, (left - right) / abs(right)))
    return derived


def _number_tokens(text: str) -> list[str]:
    return [match.group(0) for match in _NUMBER_PATTERN.finditer(text)]


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        return [_parse_number(token) for token in _number_tokens(value)]
    if isinstance(value, dict):
        result: list[float] = []
        for child in value.values():
            result.extend(_numeric_values(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_numeric_values(child))
        return result
    return []


def _parse_number(token: str) -> float:
    numeric = float(token.rstrip("%").replace(",", ""))
    return numeric / 100 if token.endswith("%") else numeric


def _matches_evidence(token: str, allowed_values: list[float]) -> bool:
    candidate = _parse_number(token)
    return any(
        abs(candidate - allowed) <= max(0.005, abs(allowed) * 0.0005)
        for allowed in allowed_values
    )
