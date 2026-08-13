from pathlib import Path
from typing import Any

import pandas as pd

from app.agent_runtime.metric_registry import (
    data_resource_context,
    definition_for,
    metric_evidence,
    metric_catalog,
    metric_snapshot,
    required_reference_for_question,
)
from app.agent_runtime.tools import (
    OPERATING_TOOLS,
    OperatingToolContext,
    execute_operating_tools,
)


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _all_metrics() -> dict[str, Any]:
    context = OperatingToolContext(
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
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
    return execute_operating_tools(list(OPERATING_TOOLS), context)


def _public_paths(value: Any, path: str = "metrics") -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, child in value.items():
            if not str(key).startswith("_"):
                result.extend(_public_paths(child, f"{path}.{key}"))
        return result
    return [path]


def test_every_public_tool_output_path_has_a_metric_definition():
    paths = _public_paths(_all_metrics())

    missing = [path for path in paths if definition_for(path) is None]

    assert missing == []


def test_catalog_exposes_business_semantics_not_only_runtime_types():
    catalog = metric_catalog(
        _all_metrics(), question="外卖贡献率为什么偏低？"
    )
    by_ref = {item["ref"]: item for item in catalog}
    margin = by_ref["metrics.channels.delivery_contribution_margin"]

    assert margin["label"] == "外卖贡献率"
    assert margin["unit"] == "ratio"
    assert margin["formula"] == "delivery_contribution_profit / delivery_revenue"
    assert margin["benchmark_required"] is True
    assert "房租" in margin["excludes"]
    assert "metrics.discounts.discounted_order_share" not in by_ref


def test_array_metric_definitions_include_item_schemas():
    definition = definition_for("metrics.channels.channels")

    assert definition is not None
    assert definition.item_schema is not None
    assert definition.item_schema["contribution_margin"] == "贡献利润除以渠道营收"


def test_synthesis_evidence_combines_values_and_annotations_without_duplication():
    evidence = metric_evidence(_all_metrics(), sections={"channels"})
    by_ref = {item["ref"]: item for item in evidence}

    margin = by_ref["metrics.channels.delivery_contribution_margin"]
    assert margin["value"] == 0.367
    assert margin["label"] == "外卖贡献率"
    assert by_ref["metrics.channels.channels"]["label"] == "渠道明细"


def test_question_snapshot_contains_relevant_values_and_semantics_only():
    snapshot = metric_snapshot(
        _all_metrics(), question="外卖贡献率为什么偏低？"
    )
    by_ref = {item["ref"]: item for item in snapshot}

    assert by_ref["metrics.channels.delivery_contribution_margin"]["value"] == 0.367
    assert by_ref["metrics.channels.delivery_contribution_margin"]["label"] == "外卖贡献率"
    assert "metrics.revenue.total_revenue" not in by_ref


def test_data_resource_context_states_coverage_and_missing_benchmarks():
    resources = data_resource_context(
        _all_metrics(), question="外卖贡献率为什么偏低？"
    )

    assert resources["coverage"] == {
        "date_start": "2026-06-01",
        "date_end": "2026-06-04",
        "order_count": 8,
        "review_count": 4,
        "observed_days": 4,
    }
    assert resources["benchmarks"] == {}
    assert "metrics.channels.delivery_contribution_margin" in resources["benchmark_status"]["missing_for"]
    assert "Do not claim causation" in resources["causal_limit"]


def test_data_resource_context_exposes_merchant_targets_as_citable_evidence():
    metrics = {
        **_all_metrics(),
        "_targets": {"metrics.channels.delivery_contribution_margin": 0.4},
    }

    resources = data_resource_context(
        metrics, question="外卖贡献率是否偏低？"
    )

    assert resources["target_evidence"] == [
        {
            "ref": "targets.metrics.channels.delivery_contribution_margin",
            "metric_ref": "metrics.channels.delivery_contribution_margin",
            "value": 0.4,
        }
    ]
    assert resources["benchmark_status"]["missing_for"] == [
        "metrics.channels.delivery_commission_rate",
        "metrics.channels.delivery_packaging_per_order",
        "metrics.channels.delivery_revenue",
        "metrics.channels.delivery_revenue_share",
        "metrics.channels.delivery_food_cost",
        "metrics.channels.delivery_platform_fee",
        "metrics.channels.delivery_packaging_cost",
        "metrics.channels.delivery_contribution_profit",
    ]


def test_question_resolves_to_the_exact_required_metric_reference():
    reference = required_reference_for_question(
        "外卖贡献率为什么偏低？", _all_metrics()
    )

    assert reference == "metrics.channels.delivery_contribution_margin"


def test_every_operating_tool_has_a_complete_contract():
    for tool in OPERATING_TOOLS.values():
        assert tool.output_section
        assert tool.use_when
        assert tool.limitations
