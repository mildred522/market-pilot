from __future__ import annotations

import json

from app.agent_runtime.contracts import AnalysisMode, AgentPlan, PlannedTool
from app.agent_runtime.llm_client import LlmClient, LlmError
from app.agent_runtime.metric_registry import definitions_for_sections
from app.agent_runtime.plan_policy import (
    apply_operating_plan_policy,
    focused_fallback_tools,
)
from app.agent_runtime.prompts import PLANNER_SYSTEM_PROMPT
from app.agent_runtime.tools import (
    OperatingToolContext,
    available_tool_specs,
)


def create_operating_plan(
    *,
    client: LlmClient,
    question: str,
    context: OperatingToolContext,
    analysis_mode: AnalysisMode = "full",
) -> tuple[AgentPlan, bool, list[str]]:
    fallback = _fallback_plan(context, question, analysis_mode)
    if not client.configured:
        return fallback, False, ["planner: LLM not configured"]

    catalog = _tool_catalog(context)
    user_prompt = json.dumps(
        {
            "question": question,
            "stage": "operating",
            "analysis_mode": analysis_mode,
            "available_inputs": sorted(context.available_inputs),
            "tool_catalog": catalog,
        },
        ensure_ascii=False,
    )
    try:
        candidate = client.generate_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AgentPlan,
            temperature=0.1,
        )
        return apply_operating_plan_policy(
            candidate, context, analysis_mode=analysis_mode
        ), True, []
    except (LlmError, ValueError) as error:
        return fallback, False, [f"planner: {error}"]


def create_operating_replan(
    *,
    client: LlmClient,
    question: str,
    context: OperatingToolContext,
    analysis_mode: AnalysisMode,
    previous_plan: AgentPlan,
    failed_tools: list[dict[str, str | bool | None]],
) -> tuple[AgentPlan | None, bool, list[str]]:
    if not client.configured:
        return None, False, ["replanner: LLM not configured"]
    user_prompt = json.dumps(
        {
            "question": question,
            "stage": "operating",
            "analysis_mode": analysis_mode,
            "replan_attempt": 1,
            "previous_plan": previous_plan.model_dump(mode="json"),
            "failed_tools": failed_tools,
            "available_inputs": sorted(context.available_inputs),
            "tool_catalog": _tool_catalog(context),
        },
        ensure_ascii=False,
    )
    try:
        candidate = client.generate_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AgentPlan,
            temperature=0.1,
        )
        return (
            apply_operating_plan_policy(
                candidate, context, analysis_mode=analysis_mode
            ),
            True,
            [],
        )
    except (LlmError, ValueError) as error:
        return None, False, [f"replanner: {error}"]


def _tool_catalog(context: OperatingToolContext) -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "required_inputs": list(spec.required_inputs),
            "output_section": spec.output_section,
            "use_when": list(spec.use_when),
            "limitations": list(spec.limitations),
            "output_contract": definitions_for_sections(
                {spec.output_section}, compact=True
            ),
        }
        for spec in available_tool_specs(context)
    ]


def _fallback_plan(
    context: OperatingToolContext,
    question: str,
    analysis_mode: AnalysisMode,
) -> AgentPlan:
    tools = (
        focused_fallback_tools(question, context)
        if analysis_mode == "focused"
        else [
            PlannedTool(name=spec.name, reason="deterministic fallback analysis")
            for spec in available_tool_specs(context)
        ]
    )
    return AgentPlan(
        intent="operating_diagnosis",
        goal=(
            "answer the focused operating question"
            if analysis_mode == "focused"
            else "generate a complete deterministic operating diagnosis"
        ),
        tools=tools,
        missing_inputs=[],
        requires_external_api=False,
    )
