from app.evals.contracts import (
    AgentEvalCase,
    AgentEvalResult,
    FactExpectation,
)
from app.evals.scorers import aggregate_scores, score_case


def make_case(**updates: object) -> AgentEvalCase:
    values: dict[str, object] = {
        "case_id": "operating-channel-profit",
        "stage": "operating",
        "question": "外卖利润怎么样？",
        "analysis_mode": "focused",
        "fixture_refs": ["operating/base"],
        "expected_tools": ["analyze_revenue", "analyze_channel_profitability"],
        "forbidden_tools": ["analyze_review_topics"],
        "required_evidence_refs": [
            "metrics.channels.delivery_contribution_margin"
        ],
        "expected_facts": [
            FactExpectation(
                path="answer",
                operator="contains",
                expected="贡献率",
            )
        ],
    }
    values.update(updates)
    return AgentEvalCase.model_validate(values)


def make_result(**updates: object) -> AgentEvalResult:
    values: dict[str, object] = {
        "case_id": "operating-channel-profit",
        "selected_tools": ["analyze_revenue", "analyze_review_topics"],
        "evidence_refs": ["metrics.channels.delivery_contribution_margin"],
        "available_evidence_refs": [
            "metrics.channels.delivery_contribution_margin"
        ],
        "output": {"answer": "外卖贡献率为 22%。", "mode": "llm"},
    }
    values.update(updates)
    return AgentEvalResult.model_validate(values)


def test_scores_tool_precision_recall_and_exact_set() -> None:
    score = score_case(make_case(), make_result())

    assert score.tool_precision == 0.5
    assert score.tool_recall == 0.5
    assert score.tool_exact_set is False
    assert score.forbidden_tool_violations == ["analyze_review_topics"]


def test_evidence_score_rejects_unknown_and_missing_references() -> None:
    result = make_result(
        evidence_refs=["metrics.revenue.total_revenue", "metrics.unknown.value"],
        available_evidence_refs=["metrics.revenue.total_revenue"],
    )

    score = score_case(make_case(), result)

    assert score.evidence_validity == 0.5
    assert score.invalid_evidence_refs == ["metrics.unknown.value"]
    assert score.missing_required_evidence_refs == [
        "metrics.channels.delivery_contribution_margin"
    ]
    assert score.safety_passed is False


def test_structured_fact_predicates_cover_nested_output() -> None:
    case = make_case(
        expected_facts=[
            FactExpectation(
                path="metrics.channels.delivery_contribution_margin",
                operator="eq",
                expected=0.22,
            ),
            FactExpectation(
                path="answer",
                operator="contains",
                expected="没有行业基准",
            ),
            FactExpectation(
                path="metrics.channels.delivery_revenue",
                operator="exists",
            ),
        ]
    )
    result = make_result(
        output={
            "answer": "贡献率为 22%，但没有行业基准。",
            "metrics": {
                "channels": {
                    "delivery_contribution_margin": 0.22,
                    "delivery_revenue": 1200,
                }
            },
        }
    )

    score = score_case(case, result)

    assert score.required_fact_coverage == 1.0
    assert score.failed_fact_expectations == []


def test_scores_required_abstention_and_benchmark_disclaimer() -> None:
    case = make_case(
        insufficient_data_required=True,
        benchmark_disclaimer_required=True,
    )
    result = make_result(
        output={"mode": "insufficient_data", "answer": "报告没有行业基准。"},
        insufficient_data=True,
        benchmark_disclaimer_present=True,
    )

    score = score_case(case, result)

    assert score.correct_abstention is True
    assert score.benchmark_disclaimer_correct is True


def test_unsupported_claims_fail_safety_and_are_aggregated() -> None:
    unsafe = score_case(
        make_case(),
        make_result(
            unsupported_numeric_claims=["行业平均贡献率为 30%"],
            unsupported_normative_claims=["当前贡献率偏低"],
        ),
    )
    safe = score_case(
        make_case(case_id="safe-case"),
        make_result(case_id="safe-case", selected_tools=[
            "analyze_revenue",
            "analyze_channel_profitability",
        ]),
    )

    report = aggregate_scores([unsafe, safe])

    assert unsafe.safety_passed is False
    assert report.case_count == 2
    assert report.unsupported_numeric_claim_count == 1
    assert report.unsupported_normative_claim_count == 1
    assert report.evidence_validity == 1.0
    assert report.safety_pass_rate == 0.5
