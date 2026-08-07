import pandas as pd

from app.agents.executor import execute_plan
from app.agents.planner import create_plan
from app.agents.router import detect_stage
from app.agents.state import AgentState
from app.agents.synthesizer import synthesize
from app.agents.verifier import verify_evidence


class AgentService:
    def analyze_operating(
        self,
        *,
        project_id: int,
        question: str,
        orders: pd.DataFrame,
        menu: pd.DataFrame,
        reviews: pd.DataFrame,
    ) -> dict[str, object]:
        state = AgentState(
            project_id=project_id,
            question=question,
            stage=detect_stage(question),
        )
        state = create_plan(state)
        state = execute_plan(state, orders=orders, menu=menu, reviews=reviews)
        state = synthesize(state)
        state = verify_evidence(state)

        return {
            "project_id": state.project_id,
            "stage": state.stage,
            "intent": state.intent,
            "plan": state.plan,
            "summary": state.summary,
            "metrics": state.tool_results,
            "evidence": state.evidence,
            "actions": state.actions,
            "warnings": state.warnings,
        }
