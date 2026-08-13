from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from app.evals.offline import OfflineAgentAdapter
from app.evals.reporting import AgentEvalSafetyError, assert_safety_gate, write_report
from app.evals.runner import load_cases, run_cases


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = BACKEND_ROOT.parent / "outputs" / "evals"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline Agent golden cases.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the JSON and Markdown reports.",
    )
    arguments = parser.parse_args(argv)
    case_dir = BACKEND_ROOT / "evals" / "cases"
    cases = [
        *load_cases(case_dir / "operating.json"),
        *load_cases(case_dir / "followup.json"),
    ]
    report = run_cases(cases, OfflineAgentAdapter(BACKEND_ROOT))
    json_path, markdown_path = write_report(report, arguments.output_dir)
    try:
        assert_safety_gate(report)
    except AgentEvalSafetyError as error:
        print(f"Agent evaluation safety gate failed: {error}")
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 1
    print(f"Agent evaluation safety gate passed ({report.summary.case_count} cases).")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
