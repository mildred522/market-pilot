from __future__ import annotations

from pathlib import Path

from app.evals.contracts import AgentEvalReport


class AgentEvalSafetyError(RuntimeError):
    pass


def assert_safety_gate(report: AgentEvalReport) -> None:
    failures: list[str] = []
    for execution in report.cases:
        score = execution.score
        if (
            score.invalid_evidence_refs
            or score.missing_required_evidence_refs
            or score.forbidden_evidence_violations
        ):
            failures.append(f"{execution.case.case_id}: invalid evidence")
        if score.unsupported_numeric_claim_count:
            failures.append(f"{execution.case.case_id}: unsupported numeric claim")
        if score.unsupported_normative_claim_count:
            failures.append(f"{execution.case.case_id}: unsupported normative claim")
        if (
            execution.case.insufficient_data_required
            and not execution.result.insufficient_data
        ):
            failures.append(f"{execution.case.case_id}: required abstention missing")
    if failures:
        raise AgentEvalSafetyError("; ".join(failures))


def render_markdown(report: AgentEvalReport) -> str:
    summary = report.summary
    lines = [
        "# Agent Evaluation Baseline",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {summary.case_count} |",
        f"| Tool precision | {_format(summary.tool_precision)} |",
        f"| Tool recall | {_format(summary.tool_recall)} |",
        f"| Tool exact-set accuracy | {_format(summary.tool_exact_set_accuracy)} |",
        f"| Evidence validity | {_format(summary.evidence_validity)} |",
        f"| Required fact coverage | {_format(summary.required_fact_coverage)} |",
        f"| Correct abstention rate | {_format(summary.correct_abstention_rate)} |",
        f"| Benchmark disclaimer accuracy | {_format(summary.benchmark_disclaimer_accuracy)} |",
        f"| Unsupported numeric claims | {summary.unsupported_numeric_claim_count} |",
        f"| Unsupported normative claims | {summary.unsupported_normative_claim_count} |",
        f"| Safety pass rate | {_format(summary.safety_pass_rate)} |",
        f"| Overall pass rate | {_format(summary.pass_rate)} |",
        "",
        "## Focused planning baseline",
        "",
    ]
    mismatches = [
        execution
        for execution in report.cases
        if execution.case.analysis_mode == "focused"
        and not execution.score.tool_exact_set
    ]
    if mismatches:
        lines.extend(
            [
                "Focused cases below selected a broader or different tool set than expected.",
                "They are recorded as planning-quality failures and do not bypass the safety gate.",
                "",
                "| Case | Expected tools | Selected tools | Precision | Recall |",
                "| --- | --- | --- | ---: | ---: |",
            ]
        )
        for execution in mismatches:
            lines.append(
                "| "
                + " | ".join(
                    (
                        execution.case.case_id,
                        _tool_names(execution.case.expected_tools),
                        _tool_names(execution.result.selected_tools),
                        _format(execution.score.tool_precision),
                        _format(execution.score.tool_recall),
                    )
                )
                + " |"
            )
    else:
        lines.append("All focused cases selected the expected tool set.")

    lines.extend(
        [
            "",
            "## Case Results",
            "",
            "| Case | Stage | Safety | Facts | Tool set |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for execution in report.cases:
        lines.append(
            "| "
            + " | ".join(
                (
                    execution.case.case_id,
                    execution.case.stage,
                    "pass" if execution.score.safety_passed else "fail",
                    _format(execution.score.required_fact_coverage),
                    "exact" if execution.score.tool_exact_set else "mismatch",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_report(
    report: AgentEvalReport, output_dir: Path, *, name: str = "agent-eval-baseline"
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{name}.json"
    markdown_path = output_dir / f"{name}.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _format(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _tool_names(values: list[str]) -> str:
    return ", ".join(values) if values else "none"
