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
