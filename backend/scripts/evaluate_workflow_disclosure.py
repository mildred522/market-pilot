from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import pandas as pd

from app.agent_runtime.planning import planner_disclosure_stats
from app.agent_runtime.tools import OperatingToolContext
from app.agent_runtime.workflow_registry import (
    expand_workflow,
    workflow_candidates,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure workflow coverage and Planner catalog reduction."
    )
    parser.add_argument(
        "--cases", type=Path, default=Path("evals/cases/operating.json")
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    context = _context()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        stats = planner_disclosure_stats(case["question"], context)
        match = (
            {"workflow": "full_policy", "dimensions": []}
            if case["analysis_mode"] == "full"
            else _find_exact_workflow(
                case["question"], case["expected_tools"], context
            )
        )
        rows.append(
            {
                "case_id": case["case_id"],
                "analysis_mode": case["analysis_mode"],
                "expected_tools": case["expected_tools"],
                "representable": match is not None,
                "workflow_plan": match,
                **stats,
            }
        )
    summary = {
        "case_count": len(rows),
        "representable_count": sum(row["representable"] for row in rows),
        "representable_rate": round(
            sum(row["representable"] for row in rows) / max(1, len(rows)), 4
        ),
        "mean_catalog_reduction_percent": round(
            sum(row["reduction_percent"] for row in rows) / max(1, len(rows)), 1
        ),
        "max_catalog_characters": max(
            (row["catalog_characters"] for row in rows), default=0
        ),
        "legacy_catalog_characters": max(
            (row["legacy_catalog_characters"] for row in rows), default=0
        ),
    }
    report = {"summary": summary, "cases": rows}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), **summary}, ensure_ascii=False, indent=2))
    else:
        print(rendered)
    return 0 if summary["representable_rate"] == 1 else 1


def _find_exact_workflow(
    question: str,
    expected_tools: list[str],
    context: OperatingToolContext,
) -> dict[str, object] | None:
    expected = list(dict.fromkeys(expected_tools))
    for workflow in workflow_candidates(question, context):
        names = [item.name for item in workflow.dimensions]
        for size in range(1, min(4, len(names)) + 1):
            for selected in combinations(names, size):
                expanded = expand_workflow(workflow.name, list(selected), context)
                if set(expanded) == set(expected) and len(expanded) == len(expected):
                    return {
                        "workflow": workflow.name.value,
                        "dimensions": list(selected),
                    }
    return None


def _context() -> OperatingToolContext:
    sample = Path(__file__).resolve().parents[1] / "sample_data"
    return OperatingToolContext(
        orders=pd.read_csv(sample / "orders.csv"),
        menu=pd.read_csv(sample / "menu_items.csv"),
        reviews=pd.read_csv(sample / "reviews.csv"),
        cost_assumptions={
            "monthly_rent": 18000,
            "monthly_labor": 24000,
            "monthly_utilities": 3000,
            "monthly_marketing": 2000,
            "other_fixed_costs": 3000,
            "cash_balance": 120000,
            "delivery_commission_rate": 0.2,
            "delivery_packaging_per_order": 1.5,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
