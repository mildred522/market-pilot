import json
from pathlib import Path

import pytest

from app.evals.contracts import AgentEvalCase, AgentEvalResult
from app.evals.reporting import (
    AgentEvalSafetyError,
    assert_safety_gate,
    render_markdown,
    write_report,
)
from app.evals.runner import run_cases
from scripts.run_agent_evals import main


class ResultAdapter:
    def __init__(self, result: AgentEvalResult) -> None:
        self.result = result

    def execute(self, case: AgentEvalCase) -> AgentEvalResult:
        return self.result.model_copy(update={"case_id": case.case_id})


def case(**updates: object) -> AgentEvalCase:
    values: dict[str, object] = {
        "case_id": "report-case",
        "stage": "operating",
        "question": "只分析营收",
        "analysis_mode": "focused",
        "expected_tools": ["analyze_revenue"],
        "required_evidence_refs": ["metrics.revenue.total_revenue"],
    }
    values.update(updates)
    return AgentEvalCase.model_validate(values)


def result(**updates: object) -> AgentEvalResult:
    values: dict[str, object] = {
        "case_id": "report-case",
        "selected_tools": ["analyze_revenue", "analyze_review_topics"],
        "evidence_refs": ["metrics.revenue.total_revenue"],
        "available_evidence_refs": ["metrics.revenue.total_revenue"],
        "output": {"answer": "样本营收已经核算。"},
    }
    values.update(updates)
    return AgentEvalResult.model_validate(values)


def test_markdown_report_exposes_metrics_and_planning_baseline() -> None:
    report = run_cases([case()], ResultAdapter(result()))

    markdown = render_markdown(report)

    assert "# Agent Evaluation Baseline" in markdown
    assert "Tool precision" in markdown
    assert "0.5" in markdown
    assert "report-case" in markdown
    assert "Focused planning baseline" in markdown


def test_write_report_creates_json_and_markdown(tmp_path: Path) -> None:
    report = run_cases([case()], ResultAdapter(result()))

    json_path, markdown_path = write_report(report, tmp_path, name="baseline")

    assert json_path == tmp_path / "baseline.json"
    assert markdown_path == tmp_path / "baseline.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["case_count"] == 1
    assert "report-case" in markdown_path.read_text(encoding="utf-8")


def test_safety_gate_allows_planning_mismatch() -> None:
    report = run_cases([case()], ResultAdapter(result()))

    assert_safety_gate(report)


def test_cli_generates_the_offline_baseline(tmp_path: Path) -> None:
    exit_code = main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(
        (tmp_path / "agent-eval-baseline.json").read_text(encoding="utf-8")
    )
    assert payload["summary"]["case_count"] == 30
    assert (tmp_path / "agent-eval-baseline.md").exists()


@pytest.mark.parametrize(
    ("case_updates", "result_updates"),
    [
        ({}, {"evidence_refs": ["metrics.unknown"]}),
        ({}, {"unsupported_numeric_claims": ["行业均值为 30%"]}),
        ({}, {"unsupported_normative_claims": ["该指标偏低"]}),
        ({"insufficient_data_required": True}, {"insufficient_data": False}),
    ],
)
def test_safety_gate_rejects_hard_agent_failures(
    case_updates: dict[str, object], result_updates: dict[str, object]
) -> None:
    report = run_cases(
        [case(**case_updates)],
        ResultAdapter(result(**result_updates)),
    )

    with pytest.raises(AgentEvalSafetyError):
        assert_safety_gate(report)
