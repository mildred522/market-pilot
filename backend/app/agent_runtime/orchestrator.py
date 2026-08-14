from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd

from app.agent_runtime.contracts import (
    AnalysisMode,
    AgentPlan,
    AgentTrace,
    ReplanTrace,
)
from app.agent_runtime.llm_client import LlmClient, llm_client_from_environment
from app.agent_runtime.planning import create_operating_plan, create_operating_replan
from app.agent_runtime.prompts import PROMPT_VERSION
from app.agent_runtime.synthesis import synthesize_operating_report
from app.agent_runtime.tool_contracts import ToolExecutionBatch
from app.agent_runtime.tools import OperatingToolContext, execute_operating_tools
from app.agents.state import AgentState


@dataclass(frozen=True)
class OperatingAgentRun:
    state: AgentState
    plan: AgentPlan
    trace: AgentTrace


class OperatingAgentOrchestrator:
    def __init__(
        self,
        client: LlmClient | None = None,
        *,
        planner_client: LlmClient | None = None,
        synthesizer_client: LlmClient | None = None,
    ) -> None:
        self._planner_client = client or planner_client or llm_client_from_environment(
            "planner"
        )
        self._synthesizer_client = (
            client or synthesizer_client or llm_client_from_environment("synthesizer")
        )

    def run(
        self,
        *,
        project_id: int,
        question: str,
        analysis_mode: AnalysisMode = "full",
        orders: pd.DataFrame,
        menu: pd.DataFrame,
        reviews: pd.DataFrame,
        cost_assumptions: dict[str, Any] | None,
    ) -> OperatingAgentRun:
        started = perf_counter()
        llm_calls = []
        context = OperatingToolContext(
            orders=orders,
            menu=menu,
            reviews=reviews,
            cost_assumptions=cost_assumptions,
        )
        plan, planning_used_llm, planning_fallbacks = create_operating_plan(
            client=self._planner_client,
            question=question,
            context=context,
            analysis_mode=analysis_mode,
            metadata_sink=llm_calls,
        )
        selected_tools = [tool.name for tool in plan.tools]
        initial_plan = plan.model_copy(deep=True)
        initial_tools = list(selected_tools)
        tool_batch = execute_operating_tools(
            selected_tools,
            context,
            required_tools=(set(selected_tools) if analysis_mode == "focused" else None),
        )
        replan_count = 0
        replan_trace: ReplanTrace | None = None
        recoverable_failures = [
            item
            for item in tool_batch.executions
            if item.status == "failed" and item.recoverable
        ]
        if tool_batch.status == "failed" and recoverable_failures:
            replanned, replan_used_llm, replan_fallbacks = create_operating_replan(
                client=self._planner_client,
                question=question,
                context=context,
                analysis_mode=analysis_mode,
                previous_plan=plan,
                failed_tools=[
                    {
                        "tool_name": item.tool_name,
                        "error_code": item.error_code,
                        "recoverable": item.recoverable,
                    }
                    for item in recoverable_failures
                ],
                metadata_sink=llm_calls,
            )
            planning_used_llm = planning_used_llm or replan_used_llm
            planning_fallbacks.extend(replan_fallbacks)
            if replanned is not None:
                replan_count = 1
                completed = {
                    item.tool_name
                    for item in tool_batch.executions
                    if item.status in {"completed", "degraded"}
                }
                retry_tools = [
                    item.name for item in replanned.tools if item.name not in completed
                ]
                recovery_batch = execute_operating_tools(
                    retry_tools,
                    context,
                    required_tools=(
                        set(retry_tools) if analysis_mode == "focused" else None
                    ),
                )
                tool_batch = ToolExecutionBatch(
                    executions=[
                        *tool_batch.executions,
                        *recovery_batch.executions,
                    ],
                    stopped_early=recovery_batch.stopped_early,
                )
                plan = replanned
                replan_trace = ReplanTrace(
                    trigger="recoverable_tool_failure",
                    initial_tools=initial_tools,
                    failed_tools=[item.tool_name for item in recoverable_failures],
                    revised_tools=[tool.name for tool in replanned.tools],
                    outcome=(
                        "recovered"
                        if recovery_batch.status == "completed"
                        else "failed"
                    ),
                )
                selected_tools = list(
                    dict.fromkeys(
                        [
                            *selected_tools,
                            *(tool.name for tool in replanned.tools),
                        ]
                    )
                )
        state = AgentState(
            project_id=project_id,
            question=question,
            stage="operating",
            intent=plan.intent,
            plan=[*selected_tools, "generate_recommendations"],
            tool_results=tool_batch.successful_data,
        )
        tool_warnings = [
            warning
            for execution in tool_batch.executions
            for warning in execution.warnings
        ]
        if tool_batch.status == "failed":
            state.summary = "关键分析工具未能完成，当前数据不足以生成可靠经营诊断。"
            state.actions = ["检查上传数据的必填字段和格式后重新运行分析"]
            state.warnings = tool_warnings
            synthesis_used_llm = False
            synthesis_fallbacks = [
                "synthesizer: skipped after required tool failure"
            ]
        else:
            state, synthesis_used_llm, synthesis_fallbacks = synthesize_operating_report(
                client=self._synthesizer_client,
                state=state,
                plan=plan,
                metadata_sink=llm_calls,
            )
            state.warnings.extend(tool_warnings)
        if planning_used_llm and synthesis_used_llm:
            mode = "llm"
        elif planning_used_llm or synthesis_used_llm:
            mode = "hybrid"
        else:
            mode = "deterministic"
        trace = AgentTrace(
            mode=mode,
            analysis_mode=analysis_mode,
            provider=self._planner_client.provider,
            model=self._planner_client.model,
            prompt_version=PROMPT_VERSION,
            selected_tools=selected_tools,
            planning_used_llm=planning_used_llm,
            synthesis_used_llm=synthesis_used_llm,
            fallback_reasons=[*planning_fallbacks, *synthesis_fallbacks],
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
            status=tool_batch.status,
            tool_executions=[item.to_trace() for item in tool_batch.executions],
            llm_calls=llm_calls,
            replan_count=replan_count,
            replan=replan_trace,
            initial_plan=initial_plan,
            final_plan=plan,
        )
        return OperatingAgentRun(state=state, plan=plan, trace=trace)
