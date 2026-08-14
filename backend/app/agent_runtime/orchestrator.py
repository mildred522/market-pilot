from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd

from app.agent_runtime.contracts import AgentPlan, AgentTrace
from app.agent_runtime.llm_client import LlmClient, llm_client_from_environment
from app.agent_runtime.planning import create_operating_plan
from app.agent_runtime.prompts import PROMPT_VERSION
from app.agent_runtime.synthesis import synthesize_operating_report
from app.agent_runtime.tools import OperatingToolContext, execute_operating_tools
from app.agents.state import AgentState


@dataclass(frozen=True)
class OperatingAgentRun:
    state: AgentState
    plan: AgentPlan
    trace: AgentTrace


class OperatingAgentOrchestrator:
    def __init__(self, client: LlmClient | None = None) -> None:
        self._client = client or llm_client_from_environment()

    def run(
        self,
        *,
        project_id: int,
        question: str,
        orders: pd.DataFrame,
        menu: pd.DataFrame,
        reviews: pd.DataFrame,
        cost_assumptions: dict[str, Any] | None,
    ) -> OperatingAgentRun:
        started = perf_counter()
        context = OperatingToolContext(
            orders=orders,
            menu=menu,
            reviews=reviews,
            cost_assumptions=cost_assumptions,
        )
        plan, planning_used_llm, planning_fallbacks = create_operating_plan(
            client=self._client,
            question=question,
            context=context,
        )
        selected_tools = [tool.name for tool in plan.tools]
        tool_batch = execute_operating_tools(selected_tools, context)
        state = AgentState(
            project_id=project_id,
            question=question,
            stage="operating",
            intent=plan.intent,
            plan=[*selected_tools, "generate_recommendations"],
            tool_results=tool_batch.successful_data,
        )
        state, synthesis_used_llm, synthesis_fallbacks = synthesize_operating_report(
            client=self._client,
            state=state,
            plan=plan,
        )
        if planning_used_llm and synthesis_used_llm:
            mode = "llm"
        elif planning_used_llm or synthesis_used_llm:
            mode = "hybrid"
        else:
            mode = "deterministic"
        trace = AgentTrace(
            mode=mode,
            provider=self._client.provider,
            model=self._client.model,
            prompt_version=PROMPT_VERSION,
            selected_tools=selected_tools,
            planning_used_llm=planning_used_llm,
            synthesis_used_llm=synthesis_used_llm,
            fallback_reasons=[*planning_fallbacks, *synthesis_fallbacks],
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
        )
        return OperatingAgentRun(state=state, plan=plan, trace=trace)
