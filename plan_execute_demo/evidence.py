from __future__ import annotations

import re
from typing import Any

from .models import EvidenceFact, Finding, ToolResult


_LABELS = {
    "total_revenue": "样本期总营收",
    "order_count": "订单量",
    "avg_order_value": "客单价",
    "observed_gross_margin": "观察期毛利率",
    "monthly_fixed_cost": "演示月固定成本",
    "break_even_monthly_revenue": "月保本营收",
}
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?")


def build_evidence(results: list[ToolResult]) -> tuple[dict[str, Any], tuple[EvidenceFact, ...]]:
    metrics: dict[str, Any] = {}
    facts: list[EvidenceFact] = []
    for result in results:
        if result.status != "completed":
            continue
        metrics[result.tool] = result.metrics
        for path, value in _leaf_values(result.metrics, f"metrics.{result.tool}"):
            facts.append(
                EvidenceFact(
                    id=f"E{len(facts) + 1}",
                    path=path,
                    label=_LABELS.get(path.rsplit(".", 1)[-1], path),
                    value=value,
                )
            )
    return metrics, tuple(facts)


def validate_findings(findings: tuple[Finding, ...], evidence: tuple[EvidenceFact, ...]) -> None:
    by_id = {fact.id: fact for fact in evidence}
    for finding in findings:
        if not finding.evidence_ids:
            raise ValueError("finding_without_evidence")
        cited = [by_id.get(item) for item in finding.evidence_ids]
        if any(item is None for item in cited):
            raise ValueError("unknown_evidence_id")
        permitted = {
            rendered
            for fact in cited
            for rendered in _numeric_renderings(fact.value)  # type: ignore[union-attr]
        }
        unsupported = [
            token for token in _NUMBER.findall(finding.text) if token not in permitted
        ]
        if unsupported:
            raise ValueError(f"unsupported_number:{unsupported[0]}")


def evidence_id_for(evidence: tuple[EvidenceFact, ...], path: str) -> str:
    for fact in evidence:
        if fact.path == path:
            return fact.id
    raise ValueError(f"missing_evidence:{path}")


def _leaf_values(value: Any, path: str):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaf_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaf_values(child, f"{path}.{index}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield path, value


def _numeric_renderings(value: Any) -> set[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return set()
    number = float(value)
    rendered = {str(value), f"{number:.1f}", f"{number:.2f}"}
    if 0 <= number <= 1:
        rendered.update({f"{number * 100:.1f}%", f"{number * 100:.2f}%"})
    return rendered
