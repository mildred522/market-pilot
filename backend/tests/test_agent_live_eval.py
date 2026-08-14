import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import pytest

from app.agent_runtime.llm_client import llm_client_from_environment
from app.agent_runtime.metric_registry import metric_catalog
from app.services.agent_service import AgentService


BACKEND_ROOT = Path(__file__).resolve().parents[1]
LIVE_ENABLED = os.getenv("RUN_AGENT_LIVE_EVALS") == "1"
METRIC_REFERENCE = re.compile(r"metrics\.[A-Za-z0-9_.]+")


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_AGENT_LIVE_EVALS=1 to spend model quota on live evaluation",
)
def test_opt_in_live_agent_evaluation():
    client = llm_client_from_environment("planner")
    assert client.configured, "live evaluation requires a configured Agent model"
    cases = json.loads(
        (BACKEND_ROOT / "evals/live/agent_live_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(cases) >= 10

    orders = pd.read_csv(BACKEND_ROOT / "sample_data/orders.csv")
    menu = pd.read_csv(BACKEND_ROOT / "sample_data/menu_items.csv")
    reviews = pd.read_csv(BACKEND_ROOT / "sample_data/reviews.csv")
    runs = []
    selections: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for repeat in range(3):
        for case in cases:
            report = AgentService().analyze_operating(
                project_id=1,
                question=case["question"],
                analysis_mode="focused",
                orders=orders,
                menu=menu,
                reviews=reviews,
                cost_assumptions=_cost_assumptions(),
            )
            trace = report["agent_trace"]
            selected = tuple(trace["selected_tools"])
            selections[case["case_id"]].append(selected)
            references = {
                ref
                for item in report["evidence"]
                for ref in METRIC_REFERENCE.findall(str(item))
            }
            available = {item["ref"] for item in metric_catalog(report["metrics"])}
            calls = trace["llm_calls"]
            runs.append(
                {
                    "case_id": case["case_id"],
                    "repeat": repeat + 1,
                    "schema_success": bool(report.get("summary") and calls),
                    "evidence_valid": references <= available,
                    "selected_tools": list(selected),
                    "duration_ms": trace["duration_ms"],
                    "input_tokens": sum(call.get("input_tokens") or 0 for call in calls),
                    "output_tokens": sum(call.get("output_tokens") or 0 for call in calls),
                    "total_tokens": sum(call.get("total_tokens") or 0 for call in calls),
                }
            )

    summary = _summarize(runs, selections)
    output = {"case_count": len(cases), "repeats": 3, "summary": summary, "runs": runs}
    output_dir = BACKEND_ROOT.parent / "outputs/evals"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "agent-live-eval.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    assert summary["schema_success_rate"] >= 0.9
    assert summary["evidence_validity"] == 1.0
    assert summary["tool_selection_stability"] >= 0.8


def _summarize(runs, selections):
    count = len(runs)
    input_tokens = sum(item["input_tokens"] for item in runs)
    output_tokens = sum(item["output_tokens"] for item in runs)
    input_rate = float(os.getenv("AGENT_LIVE_INPUT_USD_PER_MILLION", "0"))
    output_rate = float(os.getenv("AGENT_LIVE_OUTPUT_USD_PER_MILLION", "0"))
    stability = sum(
        Counter(values).most_common(1)[0][1] / len(values)
        for values in selections.values()
    ) / len(selections)
    return {
        "schema_success_rate": round(
            sum(item["schema_success"] for item in runs) / count, 4
        ),
        "evidence_validity": round(
            sum(item["evidence_valid"] for item in runs) / count, 4
        ),
        "tool_selection_stability": round(stability, 4),
        "average_latency_ms": round(
            sum(item["duration_ms"] for item in runs) / count, 2
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": sum(item["total_tokens"] for item in runs),
        "estimated_cost_usd": round(
            input_tokens * input_rate / 1_000_000
            + output_tokens * output_rate / 1_000_000,
            6,
        ),
        "pricing": {
            "input_usd_per_million": input_rate,
            "output_usd_per_million": output_rate,
        },
    }


def _cost_assumptions() -> dict[str, float]:
    return {
        "monthly_rent": 18000.0,
        "monthly_labor": 24000.0,
        "monthly_utilities": 3000.0,
        "monthly_marketing": 2000.0,
        "other_fixed_costs": 3000.0,
        "cash_balance": 120000.0,
        "delivery_commission_rate": 0.2,
        "delivery_packaging_per_order": 1.5,
    }
