from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from .models import Plan, ToolResult
from .tools import analyze_menu, analyze_revenue, analyze_survival


ToolRunner = Callable[[list[dict[str, str]], list[dict[str, str]]], dict[str, Any]]
ALLOWED_RUNNERS: dict[str, ToolRunner] = {
    "revenue": analyze_revenue,
    "menu": analyze_menu,
    "survival": analyze_survival,
}


def execute_plan(
    plan: Plan, orders: list[dict[str, str]], menu: list[dict[str, str]]
) -> tuple[list[ToolResult], bool]:
    """Run only server-owned tool names and stop on a failed required step."""
    results: list[ToolResult] = []
    fallback_used = False
    for item in plan.items:
        started = perf_counter()
        runner = ALLOWED_RUNNERS.get(item.tool)
        if runner is None:
            results.append(
                ToolResult(item.tool, "blocked", {}, _duration_ms(started), "tool_not_allowed")
            )
            fallback_used = True
            break
        try:
            metrics = runner(orders, menu)
        except (KeyError, ValueError, ZeroDivisionError) as error:
            results.append(
                ToolResult(item.tool, "failed", {}, _duration_ms(started), type(error).__name__)
            )
            fallback_used = True
            break
        results.append(ToolResult(item.tool, "completed", metrics, _duration_ms(started)))
    return results, fallback_used


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
