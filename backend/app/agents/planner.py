from app.agents.state import AgentState


def create_plan(state: AgentState) -> AgentState:
    if state.stage == "operating":
        state.intent = "operating_diagnosis"
        state.plan = [
            "analyze_revenue",
            "analyze_menu_matrix",
            "analyze_review_topics",
            "generate_recommendations",
        ]
    else:
        state.intent = "pre_open_feasibility"
        state.plan = [
            "estimate_break_even",
            "evaluate_investment_pressure",
            "evaluate_franchise_risk",
            "generate_recommendations",
        ]
    return state
