from __future__ import annotations

import csv
from pathlib import Path

from .composer import compose_with_optional_llm
from .evidence import build_evidence, validate_findings
from .executor import execute_plan
from .ingestion import parse_csv
from .models import DemoReport
from .planner import build_plan, replan_after_failure


_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORDERS = _ROOT / "backend" / "sample_data" / "orders.csv"
DEFAULT_MENU = _ROOT / "backend" / "sample_data" / "menu_items.csv"
_ORDER_FIELDS = {"order_id", "item_name", "quantity", "actual_amount"}
_MENU_FIELDS = {"item_name", "unit_cost"}


def run_demo(
    question: str,
    *,
    mode: str = "focused",
    orders_path: Path = DEFAULT_ORDERS,
    menu_path: Path = DEFAULT_MENU,
    orders: list[dict[str, str]] | None = None,
    menu: list[dict[str, str]] | None = None,
) -> DemoReport:
    if orders is None:
        orders = _load_csv(orders_path, _ORDER_FIELDS)
    if menu is None:
        menu = _load_csv(menu_path, _MENU_FIELDS)
    plan = build_plan(question, mode)
    tool_results, fallback_used = execute_plan(plan, orders, menu)
    replan = None
    failed = next((item for item in tool_results if item.status == "failed"), None)
    if failed is not None:
        replan = replan_after_failure(
            plan,
            completed_tools={item.tool for item in tool_results if item.status == "completed"},
            failed_tool=failed.tool,
        )
        if replan is not None:
            recovery_results, _ = execute_plan(replan, orders, menu)
            tool_results.extend(recovery_results)
            fallback_used = True
    metrics, evidence = build_evidence(tool_results)
    findings, actions, composition_mode = compose_with_optional_llm(question, metrics, evidence)
    validate_findings(findings, evidence)
    return DemoReport(
        plan=plan,
        metrics=metrics,
        evidence=evidence,
        findings=findings,
        actions=actions,
        fallback_used=fallback_used,
        trace={
            "sample": "backend/sample_data/{orders.csv,menu_items.csv}",
            "tool_executions": [
                {
                    "tool": item.tool,
                    "status": item.status,
                    "duration_ms": item.duration_ms,
                    "warning": item.warning,
                }
                for item in tool_results
            ],
            "replan": (
                {
                    "attempted": True,
                    "failed_tool": failed.tool,
                    "replacement_tools": [item.tool for item in replan.items],
                }
                if failed is not None and replan is not None
                else {"attempted": False}
            ),
            "composition": composition_mode,
            "validation": "passed",
        },
    )


def run_demo_from_csv(
    question: str,
    *,
    orders_csv: str,
    menu_csv: str,
    mode: str = "focused",
    orders_mapping: dict[str, str] | None = None,
    menu_mapping: dict[str, str] | None = None,
) -> DemoReport:
    orders, _ = parse_csv(orders_csv, "orders", orders_mapping)
    menu, _ = parse_csv(menu_csv, "menu", menu_mapping)
    return run_demo(question, mode=mode, orders=orders, menu=menu)


def _load_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required_fields <= set(reader.fieldnames):
            missing = sorted(required_fields - set(reader.fieldnames or []))
            raise ValueError(f"sample_schema_missing:{','.join(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("sample_has_no_rows")
    return rows
