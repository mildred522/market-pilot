from __future__ import annotations

import json

from app.agent_runtime.contracts import (
    AnalysisMode,
    AgentPlan,
    LlmCallMetadata,
    PlannedTool,
)
from app.agent_runtime.llm_client import (
    LlmClient,
    LlmError,
    generate_json_with_metadata,
)
from app.agent_runtime.plan_policy import (
    apply_operating_plan_policy,
    focused_fallback_tools,
)
from app.agent_runtime.prompts import PLANNER_SYSTEM_PROMPT
from app.agent_runtime.tools import (
    OperatingToolContext,
    available_tool_specs,
)
from app.agent_runtime.workflow_registry import workflow_candidates


def create_operating_plan(
    *,
    client: LlmClient,
    question: str,
    context: OperatingToolContext,
    analysis_mode: AnalysisMode = "full",
    metadata_sink: list[LlmCallMetadata] | None = None,
) -> tuple[AgentPlan, bool, list[str]]:
    fallback = _fallback_plan(context, question, analysis_mode)
    if not client.configured:
        return fallback, False, ["planner: LLM not configured"]

    catalog = _workflow_catalog(question, context)
    user_prompt = json.dumps(
        {
            "question": question,
            "stage": "operating",
            "analysis_mode": analysis_mode,
            "available_inputs": sorted(context.available_inputs),
            "workflow_catalog": catalog,
            "selection_contract": {
                "preferred": "set workflow and dimensions; leave tools empty",
                "compatibility": "tools may be used only when no workflow applies",
                "policy": "the server expands workflows into allowed tools",
            },
        },
        ensure_ascii=False,
    )
    try:
        generation = generate_json_with_metadata(
            client=client,
            role="planner",
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AgentPlan,
            temperature=0.1,
        )
        if metadata_sink is not None:
            metadata_sink.append(generation.metadata)
        candidate = generation.output
        return apply_operating_plan_policy(
            candidate, context, analysis_mode=analysis_mode
        ), True, []
    except (LlmError, ValueError) as error:
        if isinstance(error, LlmError) and error.metadata and metadata_sink is not None:
            metadata_sink.append(error.metadata)
        return fallback, False, [f"planner: {error}"]


def create_operating_replan(
    *,
    client: LlmClient,
    question: str,
    context: OperatingToolContext,
    analysis_mode: AnalysisMode,
    previous_plan: AgentPlan,
    failed_tools: list[dict[str, str | bool | None]],
    metadata_sink: list[LlmCallMetadata] | None = None,
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
            "workflow_catalog": _workflow_catalog(question, context),
        },
        ensure_ascii=False,
    )
    try:
        generation = generate_json_with_metadata(
            client=client,
            role="replanner",
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AgentPlan,
            temperature=0.1,
        )
        if metadata_sink is not None:
            metadata_sink.append(generation.metadata)
        candidate = generation.output
        return (
            apply_operating_plan_policy(
                candidate, context, analysis_mode=analysis_mode
            ),
            True,
            [],
        )
    except (LlmError, ValueError) as error:
        if isinstance(error, LlmError) and error.metadata and metadata_sink is not None:
            metadata_sink.append(error.metadata)
        return None, False, [f"replanner: {error}"]


def _workflow_catalog(
    question: str, context: OperatingToolContext
) -> list[dict[str, object]]:
    available = {spec.name for spec in available_tool_specs(context)}
    return [
        workflow.planner_card(available)
        for workflow in workflow_candidates(question, context)
    ]


def planner_disclosure_stats(
    question: str, context: OperatingToolContext
) -> dict[str, int | float]:
    compact = json.dumps(
        _workflow_catalog(question, context), ensure_ascii=False
    )
    legacy = json.dumps(_legacy_tool_catalog(context), ensure_ascii=False)
    return {
        "candidate_workflow_count": len(_workflow_catalog(question, context)),
        "catalog_characters": len(compact),
        "legacy_catalog_characters": len(legacy),
        "reduction_percent": round((1 - len(compact) / max(1, len(legacy))) * 100, 1),
    }


def _legacy_tool_catalog(context: OperatingToolContext) -> list[dict[str, object]]:
    from app.agent_runtime.metric_registry import definitions_for_sections

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
