from app.agents.state import AgentState


def verify_evidence(state: AgentState) -> AgentState:
    if not state.evidence:
        state.warnings.append("诊断结论缺少证据支撑")
    if not state.actions:
        state.warnings.append("诊断报告缺少行动建议")
    return state
