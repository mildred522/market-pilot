from unittest.mock import patch

import pytest

from app.agent_runtime.budget import AgentRunBudget, BudgetTracker


def test_budget_rejects_non_positive_limits():
    with pytest.raises(ValueError):
        AgentRunBudget(max_model_calls=0)


def test_tracker_reserves_each_dimension_without_overrun():
    tracker = BudgetTracker(
        AgentRunBudget(
            max_model_calls=2,
            max_replans=1,
            max_repairs=1,
            max_external_retrievals=1,
        )
    )

    assert tracker.reserve("model_calls") is True
    assert tracker.reserve("model_calls") is True
    assert tracker.reserve("model_calls") is False
    assert tracker.reserve("external_retrievals") is True
    assert tracker.reserve("external_retrievals") is False

    snapshot = tracker.snapshot()
    assert snapshot["used"]["model_calls"] == 2
    assert snapshot["used"]["external_retrievals"] == 1
    assert snapshot["exhausted_dimensions"] == [
        "external_retrievals",
        "model_calls",
    ]


def test_tracker_marks_timeout_without_sleeping():
    with patch("app.agent_runtime.budget.perf_counter", side_effect=[10.0, 10.2, 10.2, 10.2]):
        tracker = BudgetTracker(AgentRunBudget(run_timeout_seconds=0.1))
        assert tracker.reserve("model_calls") is False
        assert "run_timeout" in tracker.snapshot()["exhausted_dimensions"]


def test_existing_calls_are_counted_and_evidence_truncation_is_sticky():
    tracker = BudgetTracker(AgentRunBudget(max_model_calls=2))
    tracker.consume_existing("model_calls", 1)
    tracker.mark_evidence_truncated(True)
    tracker.mark_evidence_truncated(False)

    assert tracker.reserve("model_calls") is True
    assert tracker.reserve("model_calls") is False
    assert tracker.snapshot()["evidence_truncated"] is True
