import json

import pytest

from app.agent_runtime.contracts import (
    FollowupAnswerSections,
    FollowupDataClaim,
    FollowupStep,
)
from app.agent_runtime.evidence_pack import build_evidence_pack
from app.agent_runtime.followup import ReportFollowupAgent
from app.agent_runtime.llm_client import LlmError, LlmOutputError


class FollowupFakeClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self, steps: list[FollowupStep]) -> None:
        self.steps = steps
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    def generate_json(
        self, *, system_prompt, user_prompt, response_model, temperature
    ):
        self.system_prompts.append(system_prompt)
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
    assert '"canonical_ref": "report.risks.0"' in client.prompts[0]


def test_followup_first_step_receives_a_cross_section_evidence_pack():
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                answer="样本总营收为 336 元，招牌拌面是明星菜品。",
                evidence_refs=[
                    "metrics.revenue.total_revenue",
                    "metrics.menu.items",
                ],
                confidence=0.94,
            )
        ]
    )

    ReportFollowupAgent(client).answer(
        question="结合营收推荐菜品",
        summary="样本经营诊断",
        metrics={
            "revenue": {"total_revenue": 336},
            "menu": {
                "items": [
                    {
                        "item_name": "招牌拌面",
                        "quantity": 6,
                        "gross_profit": 108,
                        "quadrant": "star",
                    }
                ]
            },
            "_agent": {"prompt": "must-not-leak"},
        },
        evidence=[],
        actions=[],
        risks=[],
    )

    prompt = json.loads(client.prompts[0])
    facts = prompt["evidence_pack"]["facts"]
    by_ref = {fact["canonical_ref"]: fact for fact in facts}

    assert by_ref["metrics.revenue.total_revenue"]["id"].startswith("E")
    assert by_ref["metrics.menu.items"]["value"][0]["item_name"] == "招牌拌面"
    assert "must-not-leak" not in client.prompts[0]


def test_followup_returns_structured_sections_in_one_call_without_tools():
    metrics = {
        "revenue": {"total_revenue": 336},
        "menu": {
            "items": [
                {
                    "item_name": "招牌拌面",
                    "quantity": 6,
                    "gross_profit": 108,
                    "quadrant": "star",
                }
            ]
        },
    }
    pack = build_evidence_pack(
        metrics=metrics,
        summary="样本经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="样本总营收为 336 元。",
                            evidence_ids=[
                                pack.fact_for_ref(
                                    "metrics.revenue.total_revenue"
                                ).id
                            ],
                        ),
                        FollowupDataClaim(
                            text="招牌拌面属于当前样本的明星菜品。",
                            evidence_ids=[pack.fact_for_ref("metrics.menu.items").id],
                        ),
                    ],
                    general_advice=["可以围绕招牌菜设计小规模套餐试验。"],
                    missing_information=["当前没有新品需求数据。"],
                ),
                confidence=0.94,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="结合营收推荐菜品",
        summary="样本经营诊断",
        metrics=metrics,
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["quality"] == "complete"
    assert result["steps"] == 1
    assert result["tool_calls"] == []
    assert result["evidence_refs"] == [
        "metrics.revenue.total_revenue",
        "metrics.menu.items",
    ]
    assert result["sections"]["general_advice"] == [
        "可以围绕招牌菜设计小规模套餐试验。"
    ]
    assert "基于门店数据" in result["answer"]
    assert "通用经营建议" in result["answer"]
    assert "evidence IDs" in client.system_prompts[0]


@pytest.mark.parametrize(
    ("question", "metrics", "reference", "claim_text"),
    [
        (
            "外卖渠道表现怎么样？",
            {"channels": {"delivery_revenue_share": 0.3333}},
            "metrics.channels.delivery_revenue_share",
            "样本外卖营收占比为 33.33%。",
        ),
        (
            "评价里有什么问题？",
            {"reviews": {"negative_review_count": 3}},
            "metrics.reviews.negative_review_count",
            "样本中差评数为 3 条。",
        ),
    ],
)
def test_followup_uses_same_structured_fast_path_across_metric_domains(
    question, metrics, reference, claim_text
):
    pack = build_evidence_pack(
        metrics=metrics,
        summary="经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text=claim_text,
                            evidence_ids=[pack.fact_for_ref(reference).id],
                        )
                    ],
                    general_advice=["先针对已观察到的问题做小范围经营试验。"],
                    missing_information=["当前报告没有同行基准。"],
                ),
                confidence=0.9,
            )
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question=question,
        summary="经营诊断",
        metrics=metrics,
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["quality"] == "complete"
    assert result["steps"] == 1
    assert result["tool_calls"] == []
    assert result["evidence_refs"] == [reference]
    assert result["sections"]["general_advice"]
    assert result["sections"]["missing_information"] == [
        "当前报告没有同行基准。"
    ]


def test_followup_repairs_only_invalid_claims_and_preserves_valid_claims():
    metrics = {
        "revenue": {"total_revenue": 336},
        "menu": {
            "items": [
                {
                    "item_name": "招牌拌面",
                    "quantity": 6,
                    "gross_profit": 108,
                    "quadrant": "star",
                }
            ]
        },
    }
    pack = build_evidence_pack(
        metrics=metrics,
        summary="样本经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )
    revenue_id = pack.fact_for_ref("metrics.revenue.total_revenue").id
    menu_id = pack.fact_for_ref("metrics.menu.items").id
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="样本总营收为 336 元。",
                            evidence_ids=[revenue_id],
                        ),
                        FollowupDataClaim(
                            text="附近竞品有 20 家。",
                            evidence_ids=["E99"],
                        ),
                    ],
                    general_advice=["先用现有数据做小规模验证。"],
                ),
                confidence=0.8,
            ),
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="招牌拌面属于当前样本的明星菜品。",
                            evidence_ids=[menu_id],
                        )
                    ]
                ),
                confidence=0.92,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="结合营收推荐菜品",
        summary="样本经营诊断",
        metrics=metrics,
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["quality"] == "repaired"
    assert result["steps"] == 2
    assert [item["text"] for item in result["sections"]["data_findings"]] == [
        "样本总营收为 336 元。",
        "招牌拌面属于当前样本的明星菜品。",
    ]
    assert result["sections"]["general_advice"] == [
        "先用现有数据做小规模验证。"
    ]
    assert result["claim_validation"] == {
        "valid_claim_count": 2,
        "invalid_claim_count": 0,
        "repair_attempted": True,
    }
    assert "附近竞品有 20 家" not in result["answer"]
    assert "repair_answer_claims" in client.prompts[1]


def test_followup_returns_valid_partial_answer_when_claim_repair_fails():
    metrics = {"revenue": {"total_revenue": 336}}
    pack = build_evidence_pack(
        metrics=metrics,
        summary="样本经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )
    revenue_id = pack.fact_for_ref("metrics.revenue.total_revenue").id
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="样本总营收为 336 元。",
                            evidence_ids=[revenue_id],
                        ),
                        FollowupDataClaim(
                            text="附近竞品有 20 家。",
                            evidence_ids=["E99"],
                        ),
                    ],
                    general_advice=["先验证一个成本可控的经营动作。"],
                ),
                confidence=0.8,
            ),
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="商圈客流每天有 5000 人。",
                            evidence_ids=["E98"],
                        )
                    ]
                ),
                confidence=0.6,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="下一步该怎么经营？",
        summary="样本经营诊断",
        metrics=metrics,
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["quality"] == "partial"
    assert result["steps"] == 2
    assert result["sections"]["data_findings"] == [
        {
            "text": "样本总营收为 336 元。",
            "evidence_refs": ["metrics.revenue.total_revenue"],
        }
    ]
    assert result["sections"]["general_advice"] == [
        "先验证一个成本可控的经营动作。"
    ]
    assert result["claim_validation"] == {
        "valid_claim_count": 1,
        "invalid_claim_count": 1,
        "repair_attempted": True,
    }
    assert "20 家" not in result["answer"]
    assert "5000 人" not in result["answer"]
    assert len(client.prompts) == 2


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


def test_followup_does_not_expose_candidate_when_answer_evidence_is_invalid():
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


class RepairableInvalidOutputClient:
    configured = True
    provider = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise LlmOutputError(
                "LLM returned invalid JSON",
                candidate_content=None,
                error_code="invalid_json",
            )
        return FollowupStep(
            action="answer",
            answer="应先执行报告中的止损动作。",
            evidence_refs=["report.actions.0"],
            confidence=0.8,
        )


def test_followup_repairs_one_invalid_structured_output_before_fallback():
    client = RepairableInvalidOutputClient()

    result = ReportFollowupAgent(client).answer(
        question="下一步做什么？",
        summary="样本经营诊断",
        metrics={},
        evidence=[],
        actions=["先停止低回报促销"],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["answer"] == "应先执行报告中的止损动作。"
    assert result["steps"] == 2
    assert result["agent_trace"]["output_repair_count"] == 1


def test_followup_does_not_expose_invalid_json_candidate():
    result = ReportFollowupAgent(InvalidOutputClient()).answer(
        question="下一步做什么？",
        summary="样本经营诊断",
        metrics={},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["failure_detail"]["stage"] == "invalid_json"
    assert "candidate" not in result["failure_detail"]


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


def test_followup_distinguishes_missing_local_evidence_from_missing_metrics():
    client = FollowupFakeClient(
        [FollowupStep(action="insufficient_data", answer="没有附近门店数据。")]
    )

    result = ReportFollowupAgent(client).answer(
        question="附近三公里有哪些直接竞品？",
        summary="当前报告",
        metrics={"revenue": {"total_revenue": 336}},
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "insufficient_data"
    assert result["missing_metrics"] == []
    assert result["missing_evidence"] == ["location_competitors"]
    assert result["failure_detail"]["stage"] == "evidence_availability"
    assert "商圈/选址分析" in result["answer"]


def test_followup_retries_generic_insufficient_data_when_relevant_evidence_exists():
    metrics = {
        "menu": {
            "items": [
                {
                    "item_name": "招牌拌面",
                    "quantity": 12,
                    "gross_profit": 216,
                    "quadrant": "star",
                }
            ]
        }
    }
    pack = build_evidence_pack(
        metrics=metrics,
        summary="现有菜品经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )
    menu_id = pack.fact_for_ref("metrics.menu.items").id
    client = FollowupFakeClient(
        [
            FollowupStep(
                action="insufficient_data",
                answer="当前报告没有潜在新菜品或市场偏好信息。",
            ),
            FollowupStep(
                action="answer",
                sections=FollowupAnswerSections(
                    data_findings=[
                        FollowupDataClaim(
                            text="招牌拌面是当前样本的明星菜品。",
                            evidence_ids=[menu_id],
                        )
                    ],
                    general_advice=["可以先围绕现有明星菜做小规模主推试验。"],
                    missing_information=["推荐全新菜品仍缺少市场需求和试销数据。"],
                ),
                confidence=0.9,
            ),
        ]
    )

    result = ReportFollowupAgent(client).answer(
        question="推荐一些菜品",
        summary="现有菜品经营诊断",
        metrics=metrics,
        evidence=[],
        actions=[],
        risks=[],
    )

    assert result["mode"] == "llm"
    assert result["quality"] == "complete"
    assert result["steps"] == 2
    assert result["evidence_refs"] == ["metrics.menu.items"]
    assert "招牌拌面" in result["answer"]
    assert "全新菜品" in result["answer"]
    assert "reconsider_insufficient_data" in client.prompts[1]


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
