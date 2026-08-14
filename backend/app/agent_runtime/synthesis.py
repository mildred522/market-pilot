from __future__ import annotations

import json

from app.agent_runtime.contracts import AgentPlan, CompactAgentSynthesis, LlmCallMetadata
from app.agent_runtime.llm_client import LlmClient, LlmError, generate_json_with_metadata
from app.agent_runtime.metric_registry import (
    data_resource_context,
    format_value,
    metric_evidence,
)
from app.agent_runtime.prompts import SYNTHESIZER_SYSTEM_PROMPT
from app.agents.state import AgentState
from app.agents.synthesizer import synthesize
from app.agents.verifier import verify_evidence


def synthesize_operating_report(
    *,
    client: LlmClient,
    state: AgentState,
    plan: AgentPlan,
    metadata_sink: list[LlmCallMetadata] | None = None,
) -> tuple[AgentState, bool, list[str]]:
    if not client.configured:
        return _deterministic(state), False, ["synthesizer: LLM not configured"]

    user_prompt = json.dumps(
        {
            "question": state.question,
            "intent": plan.intent,
            "goal": plan.goal,
            "selected_tools": [tool.model_dump() for tool in plan.tools],
            "metric_evidence": metric_evidence(
                state.tool_results, sections=set(state.tool_results)
            ),
            "data_resources": data_resource_context(
                state.tool_results, question=state.question
            ),
            "missing_inputs": plan.missing_inputs,
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        generation = generate_json_with_metadata(
            client=client,
            role="synthesizer",
            system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=CompactAgentSynthesis,
            temperature=0.3,
        )
        if metadata_sink is not None:
            metadata_sink.append(generation.metadata)
        result = generation.output
        _verify_finding_references(result, state.tool_results)
        state.summary = result.summary
        state.evidence = [
            f"{finding.claim}（依据：{', '.join(finding.evidence_refs)}）"
            for finding in result.findings
        ]
        state.actions = result.actions
        state.warnings = [
            *result.warnings,
            *(f"分析边界：{item}" for item in result.limitations),
        ]
        return verify_evidence(state), True, []
    except (LlmError, ValueError) as error:
        if isinstance(error, LlmError) and error.metadata and metadata_sink is not None:
            metadata_sink.append(error.metadata)
        return _deterministic(state), False, [f"synthesizer: {error}"]


def _deterministic(state: AgentState) -> AgentState:
    if not {"revenue", "menu", "reviews"} <= set(state.tool_results):
        return verify_evidence(_synthesize_partial(state))
    return verify_evidence(synthesize(state))


def _synthesize_partial(state: AgentState) -> AgentState:
    evidence = metric_evidence(
        state.tool_results,
        sections=set(state.tool_results),
        limit=6,
    )
    section_labels = {
        "revenue": "营收",
        "menu": "菜品",
        "reviews": "评论",
        "time_patterns": "时段",
        "discounts": "折扣",
        "survival": "保本与现金",
        "channels": "渠道",
    }
    labels = [
        section_labels.get(section, section)
        for section in state.tool_results
    ]
    state.summary = (
        f"已完成{'、'.join(labels)}聚焦分析；结论仅覆盖所选工具和当前上传样本。"
    )
    state.evidence = [
        (
            f"{item['label']}：{format_value(item['ref'], item['value'])}"
            f"（依据：{item['ref']}）"
        )
        for item in evidence
    ]
    state.actions = ["继续按相同口径记录相关指标，并结合门店目标进行复盘"]
    return state


def _verify_finding_references(
    result: CompactAgentSynthesis, metrics: dict[str, object]
) -> None:
    for finding in result.findings:
        for reference in finding.evidence_refs:
            if not reference.startswith("metrics."):
                raise ValueError(f"invalid evidence reference: {reference}")
            if not _reference_exists(metrics, reference.removeprefix("metrics.")):
                raise ValueError(f"unknown evidence reference: {reference}")


def _reference_exists(metrics: dict[str, object], path: str) -> bool:
    current: object = metrics
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True
