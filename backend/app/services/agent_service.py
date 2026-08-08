import pandas as pd

from app.agent_runtime.orchestrator import OperatingAgentOrchestrator


class AgentService:
    def __init__(self, orchestrator: OperatingAgentOrchestrator | None = None) -> None:
        self._orchestrator = orchestrator or OperatingAgentOrchestrator()

    def analyze_operating(
        self,
        *,
        project_id: int,
        question: str,
        orders: pd.DataFrame,
        menu: pd.DataFrame,
        reviews: pd.DataFrame,
        cost_assumptions: dict | None = None,
    ) -> dict[str, object]:
        run = self._orchestrator.run(
            project_id=project_id,
            question=question,
            orders=orders,
            menu=menu,
            reviews=reviews,
            cost_assumptions=cost_assumptions,
        )
        state = run.state
        metrics = {
            **state.tool_results,
            "_agent": run.trace.model_dump(mode="json"),
            "_agent_plan": run.plan.model_dump(mode="json"),
        }

        return {
            "project_id": state.project_id,
            "stage": state.stage,
            "intent": state.intent,
            "plan": state.plan,
            "summary": state.summary,
            "metrics": metrics,
            "evidence": state.evidence,
            "actions": state.actions,
            "warnings": state.warnings,
            "agent_trace": run.trace.model_dump(mode="json"),
        }
