from __future__ import annotations

import argparse
import json

from .engine import run_demo


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal Plan-Execute demo.")
    parser.add_argument("question", nargs="?", default="做一次完整经营体检")
    parser.add_argument("--mode", choices=("full", "focused"), default="focused")
    parser.add_argument("--json", action="store_true", help="print the full machine-readable report")
    args = parser.parse_args()
    report = run_demo(args.question, mode=args.mode)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print("Plan:", ", ".join(item.tool for item in report.plan.items))
    for finding in report.findings:
        print(f"- {finding.text} [{' '.join(finding.evidence_ids)}]")
    print("Trace:", report.trace)


if __name__ == "__main__":
    main()
