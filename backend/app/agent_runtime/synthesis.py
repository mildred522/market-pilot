from __future__ import annotations

import json

from app.agent_runtime.contracts import AgentPlan, AgentSynthesis
from app.agent_runtime.llm_client import LlmClient, LlmError
from app.agent_runtime.prompts import SYNTHESIZER_SYSTEM_PROMPT
from app.agents.state import AgentState
from app.agents.synthesizer import synthesize
from app.agents.verifier import verify_evidence


def synthesize_operating_report(
    *,
    client: LlmClient,
    state: AgentState,
    plan: AgentPlan,
) -> tuple[AgentState, bool, list[str]]:
    if not client.configured:
        return _deterministic(state), False, ["synthesizer: LLM not configured"]

    user_prompt = json.dumps(
        {
            "question": state.question,
            "intent": plan.intent,
            "goal": plan.goal,
            "selected_tools": [tool.model_dump() for tool in plan.tools],
            "metrics": state.tool_results,
            "missing_inputs": plan.missing_inputs,
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        result = client.generate_json(
            system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AgentSynthesis,
            temperature=0.3,
        )
        _verify_finding_references(result, state.tool_results)
        state.summary = result.summary
        state.evidence = [
            f"{finding.claim}（{finding.kind}；依据：{', '.join(finding.evidence_refs)}）"
            for finding in result.findings
        ]
        state.actions = [_format_action(action) for action in result.actions]
        state.warnings = [
            *result.warnings,
            *(f"分析边界：{item}" for item in result.limitations),
        ]
        return verify_evidence(state), True, []
    except (LlmError, ValueError) as error:
        return _deterministic(state), False, [f"synthesizer: {error}"]


def _deterministic(state: AgentState) -> AgentState:
    return verify_evidence(synthesize(state))


def _verify_finding_references(
    result: AgentSynthesis, metrics: dict[str, object]
) -> None:
    for finding in result.findings:
        if finding.kind in {"observed", "inferred"} and not finding.evidence_refs:
            raise ValueError("grounded finding is missing evidence references")
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


def _format_action(action: object) -> str:
    parts = [str(getattr(action, "action"))]
    metric = getattr(action, "metric")
    target = getattr(action, "target")
    deadline = getattr(action, "deadline_days")
    if metric and target:
        parts.append(f"指标：{metric}，目标：{target}")
    elif target:
        parts.append(f"目标：{target}")
    if deadline:
        parts.append(f"期限：{deadline} 天")
    return "；".join(parts)
