import pandas as pd

from app.agent_runtime.contracts import AnalysisMode
from app.agent_runtime.orchestrator import OperatingAgentOrchestrator
from app.agent_runtime.metric_registry import data_resource_context


class AgentService:
    def __init__(self, orchestrator: OperatingAgentOrchestrator | None = None) -> None:
        self._orchestrator = orchestrator or OperatingAgentOrchestrator()

    def analyze_operating(
        self,
        *,
        project_id: int,
        question: str,
        analysis_mode: AnalysisMode = "full",
        orders: pd.DataFrame,
        menu: pd.DataFrame,
        reviews: pd.DataFrame,
        cost_assumptions: dict | None = None,
    ) -> dict[str, object]:
        run = self._orchestrator.run(
            project_id=project_id,
            question=question,
            analysis_mode=analysis_mode,
            orders=orders,
            menu=menu,
            reviews=reviews,
            cost_assumptions=cost_assumptions,
        )
        state = run.state
        target_fields = {
            "target_avg_order_value": "metrics.revenue.avg_order_value",
            "target_delivery_contribution_margin": "metrics.channels.delivery_contribution_margin",
            "target_monthly_profit": "metrics.survival.projected_monthly_profit",
        }
        targets = {
            metric_path: cost_assumptions[field]
            for field, metric_path in target_fields.items()
            if cost_assumptions is not None and cost_assumptions.get(field) is not None
        }
        resource_metrics = {**state.tool_results, "_targets": targets}
        metrics = {
            **state.tool_results,
            "_agent": run.trace.model_dump(mode="json"),
            "_agent_plan": run.plan.model_dump(mode="json"),
            "_data_resources": data_resource_context(
                resource_metrics, question=question
            ),
            "_targets": targets,
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
