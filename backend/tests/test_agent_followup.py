from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.followup import ReportFollowupAgent


class FollowupFakeClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self, steps: list[FollowupStep]) -> None:
        self.steps = steps
        self.prompts: list[str] = []

    def generate_json(
        self, *, system_prompt, user_prompt, response_model, temperature
    ):
        self.prompts.append(user_prompt)
        return self.steps.pop(0)


def test_followup_agent_reads_metric_then_returns_grounded_answer():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"path": "metrics.revenue.total_revenue"},
            ),
            FollowupStep(
                action="answer",
                answer="样本总营收为 336 元。",
                evidence_refs=["metrics.revenue.total_revenue"],
                confidence=0.98,
            ),
        ]
    )
    agent = ReportFollowupAgent(client)

    result = agent.answer(
        question="总营收是多少？",
        summary="样本经营诊断",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=["订单汇总"],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["steps"] == 2
    assert result["answer"] == "样本总营收为 336 元。"
    assert result["tool_calls"] == [
        {
            "tool": "read_metric",
            "arguments": {"path": "metrics.revenue.total_revenue"},
        }
    ]
    assert "336" in client.prompts[1]


def test_followup_agent_rejects_non_whitelisted_tool():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="tool",
                tool_name="call_baidu_directly",
                arguments={},
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="重新请求百度",
        summary="已有报告",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "deterministic"
    assert "not allowed" in result["fallback_reason"]
