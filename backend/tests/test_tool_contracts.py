from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from app.agent_runtime.tool_contracts import (
    ToolExecutionBatch,
    ToolExecutionResult,
    validate_tool_output,
)
from app.agent_runtime.tools import (
    OPERATING_TOOLS,
    OperatingToolContext,
    execute_operating_tools,
)


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _context() -> OperatingToolContext:
    return OperatingToolContext(
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions=None,
    )


def test_completed_tool_result_contains_validated_data_and_evidence():
    batch = execute_operating_tools(["analyze_revenue"], _context())

    assert isinstance(batch, ToolExecutionBatch)
    result = batch.executions[0]
    assert result.tool_name == "analyze_revenue"
    assert result.output_section == "revenue"
    assert result.status == "completed"
    assert result.data["total_revenue"] == 336.0
    assert "metrics.revenue.total_revenue" in result.evidence
    assert result.warnings == []
    assert result.error_code is None
    assert result.duration_ms >= 0
    assert result.from_cache is False
    assert batch.successful_data == {"revenue": result.data}
    assert batch.status == "completed"


def test_output_validation_rejects_paths_without_a_metric_contract():
    try:
        validate_tool_output(
            tool_name="analyze_revenue",
            output_section="revenue",
            data={"invented_metric": 10},
        )
    except ValueError as error:
        assert "metric contract" in str(error)
    else:
        raise AssertionError("unknown output paths must be rejected")


def test_execution_failure_uses_safe_error_code_without_raw_exception(monkeypatch):
    secret = "database-password-123"

    def fail(_context):
        raise RuntimeError(secret)

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail),
    )

    batch = execute_operating_tools(["analyze_time_patterns"], _context())

    result = batch.executions[0]
    assert isinstance(result, ToolExecutionResult)
    assert result.status == "failed"
    assert result.data is None
    assert result.error_code == "tool_execution_failed"
    assert secret not in result.model_dump_json()
    assert batch.successful_data == {}
    assert batch.status == "degraded"


def test_required_tool_failure_stops_later_execution(monkeypatch):
    calls: list[str] = []

    def fail(_context):
        calls.append("revenue")
        raise RuntimeError("private storage details")

    def should_not_run(_context):
        calls.append("reviews")
        return {"review_count": 0, "negative_review_count": 0, "topics": {}}

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_revenue",
        replace(OPERATING_TOOLS["analyze_revenue"], runner=fail),
    )
    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_review_topics",
        replace(OPERATING_TOOLS["analyze_review_topics"], runner=should_not_run),
    )

    batch = execute_operating_tools(
        ["analyze_revenue", "analyze_review_topics"], _context()
    )

    assert calls == ["revenue"]
    assert batch.stopped_early is True
    assert batch.status == "failed"
    assert [item.tool_name for item in batch.executions] == ["analyze_revenue"]


def test_optional_tool_failure_continues_with_later_tools(monkeypatch):
    def fail(_context):
        raise RuntimeError("provider payload")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_time_patterns",
        replace(OPERATING_TOOLS["analyze_time_patterns"], runner=fail),
    )

    batch = execute_operating_tools(
        ["analyze_time_patterns", "analyze_review_topics"], _context()
    )

    assert batch.status == "degraded"
    assert [item.status for item in batch.executions] == ["failed", "completed"]
    assert set(batch.successful_data) == {"reviews"}


def test_explicit_empty_required_set_overrides_full_report_defaults(monkeypatch):
    def fail(_context):
        raise RuntimeError("revenue unavailable")

    monkeypatch.setitem(
        OPERATING_TOOLS,
        "analyze_revenue",
        replace(OPERATING_TOOLS["analyze_revenue"], runner=fail),
    )

    batch = execute_operating_tools(
        ["analyze_revenue", "analyze_review_topics"],
        _context(),
        required_tools=set(),
    )

    assert batch.stopped_early is False
    assert [item.status for item in batch.executions] == ["failed", "completed"]
