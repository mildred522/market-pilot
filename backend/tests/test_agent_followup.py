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


def test_followup_agent_can_answer_from_persisted_report_in_first_step():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="应优先处理现有中差评。",
                evidence_refs=["report.risks.0", "report.actions.0"],
                confidence=0.92,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="最优先处理什么？",
        summary="样本经营诊断",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=["订单数 8"],
        actions=["检查高峰出餐流程"],
        risks=["存在中差评"],
    )

    assert result["mode"] == "llm"
    assert result["steps"] == 1
    assert result["evidence_refs"] == ["report.risks.0", "report.actions.0"]
    assert '"ref": "report.risks.0"' in client.prompts[0]


def test_followup_agent_normalizes_legacy_summary_tool_reference():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="当前结论来自已保存报告。",
                evidence_refs=["read_report_summary"],
                confidence=0.8,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="报告结论是什么？",
        summary="样本经营诊断",
        metrics={},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["evidence_refs"] == ["report.summary"]
