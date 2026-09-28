from __future__ import annotations

from .evidence import evidence_id_for
from .models import EvidenceFact, Finding


def compose_report(
    metrics: dict[str, object], evidence: tuple[EvidenceFact, ...]
) -> tuple[tuple[Finding, ...], tuple[str, ...]]:
    findings: list[Finding] = []
    if "revenue" in metrics:
        value = metrics["revenue"]  # type: ignore[index]
        findings.append(
            Finding(
                text=(
                    f"样本期总营收为{value['total_revenue']:.2f}元，共{value['order_count']}单，"
                    f"客单价为{value['avg_order_value']:.2f}元。"
                ),
                evidence_ids=(
                    evidence_id_for(evidence, "metrics.revenue.total_revenue"),
                    evidence_id_for(evidence, "metrics.revenue.order_count"),
                    evidence_id_for(evidence, "metrics.revenue.avg_order_value"),
                ),
            )
        )
    if "menu" in metrics:
        items = metrics["menu"]["items"]  # type: ignore[index]
        top = items[0]
        findings.append(
            Finding(
                text=f"按营收排序，{top['item_name']}当前最高，为{top['revenue']:.2f}元。",
                evidence_ids=(
                    evidence_id_for(evidence, "metrics.menu.items.0.revenue"),
                ),
            )
        )
    if "survival" in metrics:
        value = metrics["survival"]  # type: ignore[index]
        findings.append(
            Finding(
                text=(
                    f"按演示固定成本，观察期毛利率为{value['observed_gross_margin'] * 100:.2f}%，"
                    f"月保本营收为{value['break_even_monthly_revenue']:.2f}元。"
                ),
                evidence_ids=(
                    evidence_id_for(evidence, "metrics.survival.observed_gross_margin"),
                    evidence_id_for(evidence, "metrics.survival.break_even_monthly_revenue"),
                ),
            )
        )
    actions = ("依据本轮选中的指标复盘；没有行业基准时不对高低作未经证实的判断。",)
    return tuple(findings), actions
