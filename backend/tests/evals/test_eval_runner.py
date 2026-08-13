import json
from pathlib import Path

import pytest

from app.evals.contracts import AgentEvalCase, AgentEvalResult
from app.evals.runner import load_cases, run_cases


def eval_case(case_id: str) -> AgentEvalCase:
    return AgentEvalCase(
        case_id=case_id,
        stage="operating",
        question="分析营收",
        analysis_mode="focused",
        expected_tools=["analyze_revenue"],
        required_evidence_refs=["metrics.revenue.total_revenue"],
    )


class RecordingAdapter:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def execute(self, case: AgentEvalCase) -> AgentEvalResult:
        self.seen.append(case.case_id)
        return AgentEvalResult(
            case_id=case.case_id,
            selected_tools=["analyze_revenue"],
            evidence_refs=["metrics.revenue.total_revenue"],
            available_evidence_refs=["metrics.revenue.total_revenue"],
            output={"metrics": {"revenue": {"total_revenue": 100}}},
        )


def test_runner_executes_cases_and_aggregates_scores() -> None:
    adapter = RecordingAdapter()

    report = run_cases([eval_case("case-a"), eval_case("case-b")], adapter)

    assert adapter.seen == ["case-a", "case-b"]
    assert [item.case.case_id for item in report.cases] == ["case-a", "case-b"]
    assert report.summary.case_count == 2
    assert report.summary.tool_exact_set_accuracy == 1.0
    assert report.summary.safety_pass_rate == 1.0


def test_runner_rejects_duplicate_case_identifiers() -> None:
    with pytest.raises(ValueError, match="duplicate evaluation case id"):
        run_cases([eval_case("same"), eval_case("same")], RecordingAdapter())


def test_load_cases_validates_json_file(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "case_id": "loaded-case",
                    "stage": "followup",
                    "question": "客单价是多少？",
                    "analysis_mode": "focused",
                    "expected_tools": ["read_metric"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert len(cases) == 1
    assert cases[0].case_id == "loaded-case"
    assert cases[0].stage == "followup"


def test_load_cases_rejects_non_array_document(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text('{"case_id": "wrong-shape"}', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON array"):
        load_cases(path)
