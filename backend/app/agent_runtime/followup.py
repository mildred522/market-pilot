from __future__ import annotations

import json
from typing import Any

from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.llm_client import LlmClient, LlmError, llm_client_from_environment
from app.agent_runtime.prompts import FOLLOWUP_SYSTEM_PROMPT, PROMPT_VERSION


READ_ONLY_TOOLS = {
    "list_metric_sections": "List available top-level metric sections.",
    "read_metric": "Read one metric by a metrics.section.field path.",
    "read_report_summary": "Read the persisted summary, evidence, risks, and actions.",
}


class ReportFollowupAgent:
    def __init__(self, client: LlmClient | None = None, max_steps: int = 3) -> None:
        self._client = client or llm_client_from_environment()
        self._max_steps = max(1, min(max_steps, 3))

    def answer(
        self,
        *,
        question: str,
        summary: str,
        metrics: dict[str, Any],
        evidence: list[str],
        actions: list[str],
        risks: list[str],
    ) -> dict[str, Any]:
        if not self._client.configured:
            return self._fallback(summary, evidence, "LLM not configured")

        observations: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        base_context = {
            "question": question,
            "report_summary": summary,
            "metric_sections": [key for key in metrics if not key.startswith("_")],
            "read_only_tools": READ_ONLY_TOOLS,
        }
        for step_number in range(1, self._max_steps + 1):
            try:
                step = self._client.generate_json(
                    system_prompt=FOLLOWUP_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {**base_context, "observations": observations},
                        ensure_ascii=False,
                        default=str,
                    ),
                    response_model=FollowupStep,
                    temperature=0.3,
                )
                if step.action == "answer":
                    self._validate_answer(step, metrics)
                    return {
                        "answer": step.answer,
                        "evidence_refs": step.evidence_refs,
                        "confidence": step.confidence,
                        "mode": "llm",
                        "steps": step_number,
                        "tool_calls": tool_calls,
                        "prompt_version": PROMPT_VERSION,
                    }
                observation = self._execute_tool(
                    step.tool_name, step.arguments, summary, metrics, evidence, actions, risks
                )
                tool_calls.append(
                    {"tool": step.tool_name, "arguments": step.arguments}
                )
                observations.append(
                    {"tool": step.tool_name, "result": observation}
                )
            except (LlmError, ValueError) as error:
                return self._fallback(summary, evidence, str(error), tool_calls)
        return self._fallback(summary, evidence, "maximum follow-up steps reached", tool_calls)

    def _execute_tool(
        self,
        name: str | None,
        arguments: dict[str, Any],
        summary: str,
        metrics: dict[str, Any],
        evidence: list[str],
        actions: list[str],
        risks: list[str],
    ) -> Any:
        if name == "list_metric_sections":
            return [key for key in metrics if not key.startswith("_")]
        if name == "read_report_summary":
            return {"summary": summary, "evidence": evidence, "actions": actions, "risks": risks}
        if name == "read_metric":
            path = arguments.get("path")
            if not isinstance(path, str) or not path.startswith("metrics."):
                raise ValueError("read_metric requires a metrics.* path")
            return _resolve_metric(metrics, path)
        raise ValueError(f"follow-up tool is not allowed: {name}")

    def _validate_answer(self, step: FollowupStep, metrics: dict[str, Any]) -> None:
        if not step.answer or not step.evidence_refs:
            raise ValueError("follow-up answer is missing text or evidence")
        for reference in step.evidence_refs:
            _resolve_metric(metrics, reference)

    def _fallback(
        self,
        summary: str,
        evidence: list[str],
        reason: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "answer": f"当前报告结论：{summary}",
            "evidence_refs": [],
            "confidence": 1.0,
            "mode": "deterministic",
            "steps": 0,
            "tool_calls": tool_calls or [],
            "fallback_reason": reason,
            "supporting_evidence": evidence[:3],
            "prompt_version": PROMPT_VERSION,
        }


def _resolve_metric(metrics: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("metrics."):
        raise ValueError(f"invalid metric reference: {reference}")
    current: Any = metrics
    for part in reference.removeprefix("metrics.").split("."):
        if part.startswith("_"):
            raise ValueError("internal agent metadata cannot be read as business evidence")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"unknown metric reference: {reference}")
    return current
