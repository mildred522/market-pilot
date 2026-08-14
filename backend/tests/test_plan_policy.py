from pathlib import Path

import pandas as pd
import pytest

from app.agent_runtime.contracts import AgentPlan, PlannedTool
from app.agent_runtime.llm_client import DisabledLlmClient
from app.agent_runtime.plan_policy import apply_operating_plan_policy
from app.agent_runtime.planning import create_operating_plan
from app.agent_runtime.tools import CORE_OPERATING_TOOLS, OperatingToolContext


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _context() -> OperatingToolContext:
    return OperatingToolContext(
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions={"cash_balance": 120000},
    )


def _plan(*tools: str) -> AgentPlan:
    return AgentPlan(
        intent="operating_diagnosis",
        goal="answer the requested operating question",
        tools=[PlannedTool(name=name, reason="needed") for name in tools],
    )


def test_full_mode_expands_candidate_to_complete_core_tool_set():
    result = apply_operating_plan_policy(
        _plan("analyze_revenue"), _context(), analysis_mode="full"
    )

    assert [tool.name for tool in result.tools] == list(CORE_OPERATING_TOOLS)


def test_focused_mode_preserves_minimum_candidate_tool_set():
    result = apply_operating_plan_policy(
        _plan("analyze_review_topics"), _context(), analysis_mode="focused"
    )

    assert [tool.name for tool in result.tools] == ["analyze_review_topics"]


def test_focused_mode_rejects_more_than_four_tools():
    with pytest.raises(ValueError, match="one to four"):
        apply_operating_plan_policy(
            _plan(*CORE_OPERATING_TOOLS[:5]),
            _context(),
            analysis_mode="focused",
        )


def test_policy_rejects_tools_outside_the_available_catalog():
    with pytest.raises(ValueError, match="not allowed"):
        apply_operating_plan_policy(
            _plan("read_arbitrary_file"), _context(), analysis_mode="focused"
        )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("只看中差评情况", ["analyze_review_topics"]),
        (
            "外卖营收占总营收多少",
            ["analyze_revenue", "analyze_channel_profitability"],
        ),
        (
            "差评是否集中在高峰时段",
            ["analyze_review_topics", "analyze_time_patterns"],
        ),
    ],
)
def test_focused_deterministic_fallback_selects_question_relevant_tools(
    question, expected
):
    plan, used_llm, _ = create_operating_plan(
        client=DisabledLlmClient(),
        question=question,
        context=_context(),
        analysis_mode="focused",
    )

    assert used_llm is False
    assert [tool.name for tool in plan.tools] == expected
