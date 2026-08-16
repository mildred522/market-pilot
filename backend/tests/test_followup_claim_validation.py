from app.agent_runtime.claim_validation import validate_answer_sections
from app.agent_runtime.contracts import FollowupAnswerSections, FollowupDataClaim
from app.agent_runtime.evidence_pack import build_evidence_pack


def _pack():
    return build_evidence_pack(
        metrics={
            "revenue": {"total_revenue": 336.0, "order_count": 8},
            "channels": {"delivery_contribution_margin": 0.367},
            "menu": {
                "items": [
                    {
                        "item_name": "招牌拌面",
                        "quantity": 6,
                        "gross_profit": 108.0,
                        "quadrant": "star",
                    }
                ]
            },
        },
        summary="样本经营诊断",
        evidence=[],
        actions=[],
        risks=[],
    )


def _id(pack, reference: str) -> str:
    return pack.fact_for_ref(reference).id


def test_claim_validation_keeps_valid_data_and_general_advice_sections():
    pack = _pack()
    sections = FollowupAnswerSections(
        data_findings=[
            FollowupDataClaim(
                text="样本总营收为 336 元，共 8 笔订单。",
                evidence_ids=[
                    _id(pack, "metrics.revenue.total_revenue"),
                    _id(pack, "metrics.revenue.order_count"),
                ],
            )
        ],
        general_advice=["可以围绕明星菜品设计小规模套餐试验。"],
        missing_information=["当前没有新品需求数据。"],
    )

    result = validate_answer_sections(sections, pack)

    assert [claim.text for claim in result.valid_claims] == [
        "样本总营收为 336 元，共 8 笔订单。"
    ]
    assert result.general_advice == ("可以围绕明星菜品设计小规模套餐试验。",)
    assert result.missing_information == ("当前没有新品需求数据。",)
    assert result.invalid_claims == ()


def test_claim_validation_rejects_only_the_claim_with_an_unknown_evidence_id():
    pack = _pack()
    sections = FollowupAnswerSections(
        data_findings=[
            FollowupDataClaim(
                text="样本总营收为 336 元。",
                evidence_ids=[_id(pack, "metrics.revenue.total_revenue")],
            ),
            FollowupDataClaim(text="附近竞品有 20 家。", evidence_ids=["E99"]),
        ]
    )

    result = validate_answer_sections(sections, pack)

    assert [claim.text for claim in result.valid_claims] == ["样本总营收为 336 元。"]
    assert result.invalid_claims[0].text == "附近竞品有 20 家。"
    assert result.invalid_claims[0].reason == "unknown_evidence_id:E99"


def test_claim_validation_rejects_an_unsupported_observed_number():
    pack = _pack()
    sections = FollowupAnswerSections(
        data_findings=[
            FollowupDataClaim(
                text="样本总营收为 999 元。",
                evidence_ids=[_id(pack, "metrics.revenue.total_revenue")],
            )
        ]
    )

    result = validate_answer_sections(sections, pack)

    assert result.valid_claims == ()
    assert result.invalid_claims[0].reason == "unsupported_number:999"


def test_claim_validation_accepts_a_formatted_ratio_from_the_cited_fact():
    pack = _pack()
    sections = FollowupAnswerSections(
        data_findings=[
            FollowupDataClaim(
                text="样本外卖贡献率为 36.7%。",
                evidence_ids=[
                    _id(pack, "metrics.channels.delivery_contribution_margin")
                ],
            )
        ]
    )

    result = validate_answer_sections(sections, pack)

    assert len(result.valid_claims) == 1
    assert result.invalid_claims == ()
