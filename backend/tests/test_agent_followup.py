from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.llm_client import LlmError, LlmOutputError


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
    assert [item["role"] for item in result["llm_calls"]] == [
        "followup",
        "followup",
    ]
    assert "prompt" not in str(result["llm_calls"]).lower()


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


def test_followup_preserves_candidate_when_answer_evidence_is_invalid():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="模型认为应该增加广告预算。",
                evidence_refs=["metrics.missing.value"],
                confidence=0.7,
            )
        ]
    )

    result = ReportFollowupAgent(client, max_steps=1).answer(
        question="下一步做什么？",
        summary="样本经营诊断",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=["订单数 8"],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "deterministic"
    assert result["failure_detail"] == {
        "stage": "answer_validation",
        "reason": "unknown metric reference: metrics.missing.value",
        "candidate": "模型认为应该增加广告预算。",
    }


class InvalidOutputClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def generate_json(self, **kwargs):
        raise LlmOutputError(
            "LLM returned invalid JSON",
            candidate_content="这是一段未包装成 JSON 的候选回答。",
            error_code="invalid_json",
        )


def test_followup_preserves_invalid_json_candidate():
    result = ReportFollowupAgent(InvalidOutputClient()).answer(
        question="下一步做什么？",
        summary="样本经营诊断",
        metrics={},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["failure_detail"]["stage"] == "invalid_json"
    assert result["failure_detail"]["candidate"] == "这是一段未包装成 JSON 的候选回答。"


def test_followup_normalizes_field_alias_and_exposes_exact_metric_catalog():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"field": "revenue.delivery_share"},
            ),
            FollowupStep(
                action="answer",
                answer="外卖营收占比为 33.33%。",
                evidence_refs=["metrics.channels.delivery_revenue_share"],
                confidence=0.96,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖营收占比是多少？",
        summary="渠道诊断",
        metrics={
            "revenue": {"total_revenue": 336},
            "channels": {"delivery_revenue_share": 0.3333},
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["tool_calls"] == [
        {
            "tool": "read_metric",
            "arguments": {"path": "metrics.channels.delivery_revenue_share"},
        }
    ]
    assert '"ref": "metrics.channels.delivery_revenue_share"' in client.prompts[0]
    assert "0.3333" in client.prompts[1]


def test_followup_returns_data_insufficient_for_metric_missing_from_old_report():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"field": "revenue.delivery_share"},
            ),
            FollowupStep(
                action="insufficient_data",
                answer="当前报告没有渠道指标。",
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖营收占比是多少？",
        summary="历史报告",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "insufficient_data"
    assert result["steps"] == 2
    assert result["missing_metrics"] == [
        "metrics.channels.delivery_revenue_share"
    ]
    assert "未包含" in result["answer"]
    assert "channels" not in result["available_sections"]


def test_followup_allows_model_to_correct_an_invalid_answer_reference():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="总营收为 336 元。",
                evidence_refs=["metrics.revenue.missing"],
                confidence=0.8,
            ),
            FollowupStep(
                action="answer",
                answer="总营收为 336 元。",
                evidence_refs=["metrics.revenue.total_revenue"],
                confidence=0.95,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="总营收是多少？",
        summary="历史报告",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["steps"] == 2
    assert "answer_validation" in client.prompts[1]


def test_followup_stops_duplicate_successful_tool_calls_with_grounded_answer():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"path": "metrics.revenue.total_revenue"},
            ),
            FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"path": "metrics.revenue.total_revenue"},
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="总营收是多少？",
        summary="历史报告",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "deterministic"
    assert result["steps"] == 2
    assert result["evidence_refs"] == ["metrics.revenue.total_revenue"]
    assert "336.00元" in result["answer"]
    assert len(result["tool_calls"]) == 1
    assert result["failure_detail"]["stage"] == "no_progress"


class TimeoutAfterToolClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return FollowupStep(
                action="tool",
                tool_name="read_metric",
                arguments={"path": "metrics.channels.delivery_commission_rate"},
            )
        raise LlmError("LLM request timed out or failed")


def test_followup_uses_channel_metrics_when_model_times_out_after_tool_call():
    result = ReportFollowupAgent(TimeoutAfterToolClient()).answer(
        question="外卖贡献率为什么偏低？",
        summary="渠道报告",
        metrics={
            "channels": {
                "channels": [],
                "delivery_revenue": 112,
                "delivery_revenue_share": 0.3333,
                "delivery_contribution_profit": 41.1,
                "delivery_contribution_margin": 0.367,
                "delivery_commission_rate": 0.2,
                "delivery_packaging_per_order": 1.5,
            }
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "deterministic"
    assert result["steps"] == 2
    assert "贡献率为36.70%" in result["answer"]
    assert "平台佣金率按20.0%计算" in result["answer"]
    assert "同行基准" in result["answer"]
    assert "metrics.channels.delivery_contribution_margin" in result["evidence_refs"]
    assert result["failure_detail"]["stage"] == "model_request"


def test_followup_prompt_includes_scalar_metric_snapshot():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="外卖营收占比为 33.33%。",
                evidence_refs=["metrics.channels.delivery_revenue_share"],
                confidence=0.95,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖营收占比是多少？",
        summary="渠道报告",
        metrics={
            "channels": {"delivery_revenue_share": 0.3333},
            "discounts": {"discounted_order_share": 0.0},
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert '"ref": "metrics.channels.delivery_revenue_share"' in client.prompts[0]
    assert '"value": 0.3333' in client.prompts[0]
    assert '"ref": "metrics.discounts.discounted_order_share"' not in client.prompts[0]


def test_followup_requires_contribution_margin_and_benchmark_disclaimer():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="外卖占比较低，所以贡献率偏低。",
                evidence_refs=["metrics.channels.delivery_revenue_share"],
                confidence=0.8,
            ),
            FollowupStep(
                action="answer",
                answer=(
                    "外卖贡献率为 36.70%；报告没有目标或同行基准，不能仅凭样本断言偏低。"
                ),
                evidence_refs=["metrics.channels.delivery_contribution_margin"],
                confidence=0.9,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖贡献率为什么偏低？",
        summary="渠道报告",
        metrics={
            "channels": {
                "delivery_revenue": 112,
                "delivery_revenue_share": 0.3333,
                "delivery_contribution_profit": 41.1,
                "delivery_contribution_margin": 0.367,
            }
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["steps"] == 2
    assert result["evidence_refs"] == [
        "metrics.channels.delivery_contribution_margin"
    ]
    assert "must cite metrics.channels.delivery_contribution_margin" in client.prompts[1]


def test_followup_derives_contribution_margin_for_historical_channel_report():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="外卖贡献率为 36.70%。",
                evidence_refs=["metrics.channels.delivery_contribution_margin"],
                confidence=0.9,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖贡献率是多少？",
        summary="历史渠道报告",
        metrics={
            "channels": {
                "delivery_revenue": 112,
                "delivery_contribution_profit": 41.1,
            }
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert '"ref": "metrics.channels.delivery_contribution_margin"' in client.prompts[0]
    assert '"value": 0.367' in client.prompts[0]


def test_followup_requires_merchant_target_reference_for_low_high_comparison():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="外卖贡献率低于商户目标。",
                evidence_refs=["metrics.channels.delivery_contribution_margin"],
                confidence=0.9,
            ),
            FollowupStep(
                action="answer",
                answer="外卖贡献率 36.7%，低于商户目标 40%。",
                evidence_refs=[
                    "metrics.channels.delivery_contribution_margin",
                    "targets.metrics.channels.delivery_contribution_margin",
                ],
                confidence=0.95,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="外卖贡献率是否偏低？",
        summary="渠道报告",
        metrics={
            "channels": {"delivery_contribution_margin": 0.367},
            "_targets": {"metrics.channels.delivery_contribution_margin": 0.4},
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["steps"] == 2
    assert "targets.metrics.channels.delivery_contribution_margin" in result["evidence_refs"]
    assert "merchant target" in client.prompts[1]
