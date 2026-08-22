from app.agent_runtime.budget import AgentRunBudget
from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.followup import ReportFollowupAgent


class ReadMetricClient:
    configured = True
    provider = "scripted"
    model = "scripted-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **_: object) -> FollowupStep:
        self.calls += 1
        return FollowupStep.model_validate(
            {
                "action": "tool",
                "tool_name": "read_metric",
                "arguments": {"path": "metrics.revenue.total_revenue"},
                "confidence": 0.8,
            }
        )


def test_followup_stops_before_model_call_when_budget_is_exhausted():
    client = ReadMetricClient()
    result = ReportFollowupAgent(
        client,
        budget=AgentRunBudget(max_model_calls=1),
    ).answer(
        question="总营收是多少",
        summary="样本报告",
        metrics={
            "revenue": {
                "total_revenue": 336.0,
                "order_count": 8,
                "avg_order_value": 42.0,
                "daily_revenue": [],
            }
        },
        evidence=["订单样本"],
        actions=[],
        risks=[],
    )

    budget = result["agent_trace"]["budget"]
    assert client.calls == 1
    assert budget["used"]["model_calls"] == 1
    assert budget["exhausted_dimensions"] == ["model_calls"]
    assert result["steps"] == 1
    assert "metrics.revenue.total_revenue" in result["evidence_refs"]


def test_followup_uses_configured_evidence_character_budget():
    client = ReadMetricClient()
    result = ReportFollowupAgent(
        client,
        max_steps=1,
        budget=AgentRunBudget(max_evidence_characters=120),
    ).answer(
        question="总营收是多少",
        summary="很长的报告摘要" * 100,
        metrics={"revenue": {"total_revenue": 336.0}},
        evidence=["证据" * 100],
        actions=[],
        risks=[],
    )

    assert result["agent_trace"]["budget"]["evidence_truncated"] is True
