import pandas as pd

from app.agents.state import AgentState
from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics
from app.tools.survival_tool import analyze_survival_line
from app.tools.channel_tool import analyze_channel_profitability
from app.tools.time_pattern_tool import analyze_time_patterns
from app.tools.discount_tool import analyze_discount_profitability


def execute_plan(
    state: AgentState,
    *,
    orders: pd.DataFrame | None = None,
    menu: pd.DataFrame | None = None,
    reviews: pd.DataFrame | None = None,
    cost_assumptions: dict | None = None,
) -> AgentState:
    if state.stage == "operating":
        if orders is None or menu is None or reviews is None:
            raise ValueError("operating analysis requires orders, menu, and reviews")
        state.tool_results = {
            "revenue": analyze_revenue(orders),
            "menu": analyze_menu_matrix(orders, menu),
            "reviews": analyze_review_topics(reviews),
            "time_patterns": analyze_time_patterns(orders),
            "discounts": analyze_discount_profitability(orders, menu),
        }
        if cost_assumptions is not None:
            state.tool_results["survival"] = analyze_survival_line(
                orders, menu, cost_assumptions
            )
            state.tool_results["channels"] = analyze_channel_profitability(
                orders, menu, cost_assumptions
            )
    return state
