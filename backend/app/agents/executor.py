import pandas as pd

from app.agents.state import AgentState
from app.tools.menu_tool import analyze_menu_matrix
from app.tools.revenue_tool import analyze_revenue
from app.tools.review_tool import analyze_review_topics


def execute_plan(
    state: AgentState,
    *,
    orders: pd.DataFrame | None = None,
    menu: pd.DataFrame | None = None,
    reviews: pd.DataFrame | None = None,
) -> AgentState:
    if state.stage == "operating":
        if orders is None or menu is None or reviews is None:
            raise ValueError("operating analysis requires orders, menu, and reviews")
        state.tool_results = {
            "revenue": analyze_revenue(orders),
            "menu": analyze_menu_matrix(orders, menu),
            "reviews": analyze_review_topics(reviews),
        }
    return state
