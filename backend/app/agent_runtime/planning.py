from __future__ import annotations

import json

from app.agent_runtime.contracts import AgentPlan, PlannedTool
from app.agent_runtime.llm_client import LlmClient, LlmError
from app.agent_runtime.prompts import PLANNER_SYSTEM_PROMPT
from app.agent_runtime.tools import (
    CORE_OPERATING_TOOLS,
    OperatingToolContext,
    available_tool_specs,
)


def create_operating_plan(
    *,
    client: LlmClient,
    question: str,
    context: OperatingToolContext,
) -> tuple[AgentPlan, bool, list[str]]:
    fallback = _fallback_plan(context)
    if not client.configured:
        return fallback, False, ["planner: LLM not configured"]

    catalog = [
        {
            "name": spec.name,
            "description": spec.description,
            "required_inputs": list(spec.required_inputs),
        }
        for spec in available_tool_specs(context)
    ]
    user_prompt = json.dumps(
        {
            "question": question,
            "stage": "operating",
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
        return _apply_plan_policy(candidate, context), True, []
    except (LlmError, ValueError) as error:
        return fallback, False, [f"planner: {error}"]


def _apply_plan_policy(
    plan: AgentPlan, context: OperatingToolContext
) -> AgentPlan:
    available = {spec.name for spec in available_tool_specs(context)}
    selected: list[PlannedTool] = []
    seen: set[str] = set()
    for tool in plan.tools:
        if tool.name not in available:
            raise ValueError(f"tool is not allowed: {tool.name}")
        if tool.name not in seen:
            selected.append(tool)
            seen.add(tool.name)
    for name in reversed(CORE_OPERATING_TOOLS):
        if name not in seen:
            selected.insert(
                0,
                PlannedTool(name=name, reason="required for a complete operating report"),
            )
            seen.add(name)
    return plan.model_copy(
        update={"tools": selected[:8], "requires_external_api": False}
    )


def _fallback_plan(context: OperatingToolContext) -> AgentPlan:
    return AgentPlan(
        intent="operating_diagnosis",
        goal="generate a complete deterministic operating diagnosis",
        tools=[
            PlannedTool(name=spec.name, reason="deterministic fallback analysis")
            for spec in available_tool_specs(context)
        ],
        missing_inputs=[],
        requires_external_api=False,
    )
