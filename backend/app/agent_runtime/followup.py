from __future__ import annotations

import json
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.agent_runtime.contracts import FollowupStep, LlmCallMetadata
from app.agent_runtime.budget import AgentRunBudget, BudgetTracker
from app.agent_runtime.claim_validation import (
    ValidatedClaim,
    unsupported_number,
    validate_answer_sections,
)
from app.agent_runtime.evidence_contracts import EvidencePack
from app.agent_runtime.evidence_pack import build_evidence_pack, extend_evidence_pack
from app.agent_runtime.followup_evidence import (
    FollowupEvidenceProvider,
    apply_followup_evidence_policy,
    execute_followup_evidence_request,
    has_replan_alternative,
)
from app.agent_runtime.llm_client import (
    LlmClient,
    LlmError,
    LlmOutputError,
    generate_json_with_metadata,
    llm_client_from_environment,
)
from app.agent_runtime.metric_registry import (
    answer_requires_benchmark_disclaimer,
    data_resource_context,
    format_value as registry_format_value,
    metric_catalog as registry_metric_catalog,
    metric_label as registry_metric_label,
    metric_snapshot as registry_metric_snapshot,
    question_requests_normative_comparison,
    relevant_sections as registry_relevant_sections,
    required_reference_for_question,
)
from app.agent_runtime.prompts import FOLLOWUP_SYSTEM_PROMPT, PROMPT_VERSION

if TYPE_CHECKING:
    from app.memory.history_service import MetricHistoryService


READ_ONLY_TOOLS = {
    "list_metric_sections": {
        "description": "List available top-level metric sections.",
        "arguments": {},
    },
    "list_metric_paths": {
        "description": "List exact public metric paths available in this report.",
        "arguments": {},
    },
    "read_metric": {
        "description": "Read one metric using an exact path from metric_catalog.",
        "arguments": {"path": "metrics.section.field"},
        "example": {"path": "metrics.revenue.total_revenue"},
    },
    "read_report_summary": {
        "description": "Read the persisted summary, evidence, risks, and actions.",
        "arguments": {},
    },
    "read_metric_history": {
        "description": "Compare one exact canonical metric with the prior analysis of the same project.",
        "arguments": {"path": "metrics.section.field"},
    },
}

EVIDENCE_CAPABILITY_DESCRIPTIONS = {
    "metric_history": "Compare a named current metric with the prior report of the same project.",
    "external_industry_context": "Read sourced city or category reference datasets.",
    "location_competitors": "Read the project's latest persisted local competitor snapshot.",
}


class RecoverableToolError(ValueError):
    def __init__(self, message: str, *, code: str, reference: str | None = None) -> None:
        self.code = code
        self.reference = reference
        super().__init__(message)


class MetricNotFoundError(RecoverableToolError):
    def __init__(self, reference: str) -> None:
        super().__init__(
            f"unknown metric reference: {reference}",
            code="metric_not_found",
            reference=reference,
        )


class ReportFollowupAgent:
    def __init__(
        self,
        client: LlmClient | None = None,
        max_steps: int = 4,
        budget: AgentRunBudget | None = None,
    ) -> None:
        self._client = client or llm_client_from_environment("followup")
        self._max_steps = max(1, min(max_steps, 4))
        self._budget = budget or AgentRunBudget()

    def answer(
        self,
        *,
        question: str,
        summary: str,
        metrics: dict[str, Any],
        evidence: list[str],
        actions: list[str],
        risks: list[str],
        conversation_context: dict[str, object] | None = None,
        history_service: MetricHistoryService | None = None,
        evidence_provider: FollowupEvidenceProvider | None = None,
        selected_memory_ids: list[int] | None = None,
        revision_context: dict[str, Any] | None = None,
        initial_llm_calls: list[LlmCallMetadata] | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        llm_calls: list[LlmCallMetadata] = list(initial_llm_calls or [])
        budget_tracker = BudgetTracker(self._budget)
        budget_tracker.consume_existing("model_calls", len(llm_calls))
        request_id = str(uuid4())
        evidence_replan_count = 0
        output_repair_count = 0
        evidence_events: list[dict[str, Any]] = []

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            failure_detail = result.get("failure_detail")
            verification_failures = []
            if isinstance(failure_detail, dict) and failure_detail.get("reason"):
                verification_failures.append(str(failure_detail["reason"])[:500])
            fallback_reason = result.get("fallback_reason")
            quality = str(result.get("quality", "complete"))
            status = "degraded" if quality in {"partial", "insufficient"} or fallback_reason else "completed"
            return {
                **result,
                "llm_calls": [item.model_dump(mode="json") for item in llm_calls],
                "agent_trace": {
                    "request_id": request_id,
                    "status": status,
                    "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
                    "llm_calls": [
                        item.model_dump(mode="json") for item in llm_calls
                    ],
                    "selected_memory_ids": list(selected_memory_ids or []),
                    "verification_failures": verification_failures,
                    "replan_count": evidence_replan_count,
                    "output_repair_count": output_repair_count,
                    "evidence_events": evidence_events,
                    "fallback_reasons": [str(fallback_reason)[:500]]
                    if fallback_reason
                    else [],
                    "budget": budget_tracker.snapshot(),
                },
            }

        metrics = _enrich_metrics(metrics)
        if not self._client.configured:
            return finish(self._fallback(summary, evidence, "LLM not configured"))

        observations: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        successful_tool_results: dict[str, Any] = {}
        metric_catalog = registry_metric_catalog(metrics, question=question)
        evidence_pack = build_evidence_pack(
            metrics=metrics,
            summary=summary,
            evidence=evidence,
            actions=actions,
            risks=risks,
            max_chars=self._budget.max_evidence_characters,
            max_facts=100,
            max_array_items=12,
        )
        budget_tracker.mark_evidence_truncated(evidence_pack.truncated)
        last_recoverable_error: RecoverableToolError | None = None
        last_answer_error: str | None = None
        last_candidate: str | None = None
        accepted_claims: list[ValidatedClaim] = []
        accepted_general_advice: list[str] = []
        accepted_missing_information: list[str] = []
        repair_attempted = False
        output_repair_attempted = False
        insufficient_retry_attempted = False
        attempted_evidence_capabilities: set[str] = set()
        retrieve_attempts = 0
        replan_pending = False
        project_profile = metrics.get("_project_profile", {})
        if not isinstance(project_profile, dict):
            project_profile = {}
        try:
            provider_capabilities = (
                evidence_provider.available_capabilities(project_profile)
                if evidence_provider is not None
                else set()
            )
        except Exception:
            provider_capabilities = set()
        base_context = {
            "question": question,
            "evidence_pack": evidence_pack.model_dump(mode="json"),
            "metric_sections": [key for key in metrics if not key.startswith("_")],
            "metric_catalog": _compact_metric_catalog(metric_catalog),
            "data_resources": data_resource_context(metrics, question=question),
            "project_profile": project_profile,
            "conversation_history": conversation_context
            or {
                "trust": "untrusted_historical_context",
                "messages": [],
            },
            "revision_context": revision_context or {},
            "evidence_capabilities": [
                {
                    "capability": capability,
                    "description": EVIDENCE_CAPABILITY_DESCRIPTIONS[capability],
                }
                for capability in EVIDENCE_CAPABILITY_DESCRIPTIONS
                if capability in provider_capabilities
                or (capability == "metric_history" and history_service is not None)
            ],
            "evidence_availability": [
                {
                    "capability": capability,
                    "available": capability in provider_capabilities
                    or (
                        capability == "metric_history"
                        and history_service is not None
                    ),
                }
                for capability in EVIDENCE_CAPABILITY_DESCRIPTIONS
            ],
            "read_only_tools": READ_ONLY_TOOLS,
        }
        for step_number in range(1, self._max_steps + 1):
            step: FollowupStep | None = None
            if not budget_tracker.reserve("model_calls"):
                reason = "agent run budget exhausted before model call"
                grounded = self._grounded_fallback(
                    question=question,
                    metrics=metrics,
                    observations=observations,
                    tool_calls=tool_calls,
                    steps=step_number - 1,
                    reason=reason,
                    failure_stage="budget_exhausted",
                )
                return finish(
                    grounded
                    or self._fallback(
                        summary,
                        evidence,
                        reason,
                        tool_calls,
                        failure_stage="budget_exhausted",
                    )
                )
            try:
                generation = generate_json_with_metadata(
                    client=self._client,
                    role="replanner" if replan_pending else "followup",
                    system_prompt=FOLLOWUP_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            **base_context,
                            "step": {
                                "number": step_number,
                                "remaining": self._max_steps - step_number,
                                "must_answer": step_number == self._max_steps,
                            },
                            "observations": observations,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    response_model=FollowupStep,
                    temperature=0.3,
                )
                llm_calls.append(generation.metadata)
                step = generation.output
                if step.action == "retrieve":
                    is_replan = retrieve_attempts > 0
                    if is_replan and (
                        not replan_pending or evidence_replan_count >= 1
                    ):
                        observations.append(
                            {
                                "action": "retrieve_rejected",
                                "error": {
                                    "code": "retrieval_budget_exhausted",
                                    "instruction": (
                                        "Answer now from available evidence and disclose "
                                        "remaining missing information."
                                    ),
                                },
                            }
                        )
                        replan_pending = False
                        continue
                    if is_replan and not budget_tracker.reserve("replans"):
                        observations.append(
                            {
                                "action": "retrieve_rejected",
                                "error": {
                                    "code": "replan_budget_exhausted",
                                    "instruction": "Answer now from available evidence.",
                                },
                            }
                        )
                        replan_pending = False
                        continue
                    decision = apply_followup_evidence_policy(
                        step.evidence_requests,
                        question=question,
                        history_available=history_service is not None,
                        provider_capabilities=provider_capabilities,
                        attempted_capabilities=attempted_evidence_capabilities,
                    )
                    if is_replan:
                        evidence_replan_count += 1
                    retrieve_attempts += 1
                    if decision.rejected:
                        observations.append(
                            {
                                "action": "evidence_plan_policy",
                                "rejected": list(decision.rejected),
                            }
                        )
                    if not decision.approved:
                        replan_pending = False
                        observations.append(
                            {
                                "action": "evidence_plan_empty",
                                "instruction": (
                                    "No evidence request was approved. Answer the supported "
                                    "part and disclose missing information."
                                ),
                            }
                        )
                        continue

                    new_materials = []
                    required_failure = False
                    requirements = {
                        request.capability: request.requirement
                        for request in decision.approved
                    }
                    for request in decision.approved:
                        attempted_evidence_capabilities.add(request.capability)
                        if not budget_tracker.reserve("external_retrievals"):
                            budget_event = {
                                "action": "retrieve_evidence",
                                "capability": request.capability,
                                "requirement": request.requirement,
                                "status": "failed",
                                "evidence_refs": [],
                                "error": {
                                    "code": "retrieval_budget_exhausted",
                                    "message": "evidence retrieval budget exhausted",
                                },
                            }
                            observations.append(budget_event)
                            evidence_events.append(budget_event)
                            required_failure = (
                                required_failure or request.requirement == "required"
                            )
                            continue
                        tool_calls.append(
                            {
                                "tool": request.capability,
                                "arguments": {"purpose": request.purpose},
                            }
                        )
                        result = execute_followup_evidence_request(
                            request,
                            question=question,
                            metrics=metrics,
                            history_service=history_service,
                            provider=evidence_provider,
                            project_profile=project_profile,
                        )
                        if result.status == "completed":
                            new_materials.extend(result.facts)
                        elif requirements[result.capability] == "required":
                            required_failure = True
                        evidence_event = {
                            "action": "retrieve_evidence",
                            "capability": result.capability,
                            "requirement": requirements[result.capability],
                            "status": result.status,
                            "evidence_refs": [
                                fact.canonical_ref for fact in result.facts
                            ],
                            "error": (
                                {
                                    "code": result.error_code,
                                    "message": result.message,
                                }
                                if result.status != "completed"
                                else None
                            ),
                        }
                        observations.append(evidence_event)
                        evidence_events.append(evidence_event)
                    if new_materials:
                        evidence_pack = extend_evidence_pack(
                            evidence_pack, new_materials
                        )
                        budget_tracker.mark_evidence_truncated(
                            evidence_pack.estimated_chars
                            > self._budget.max_evidence_characters
                        )
                        base_context["evidence_pack"] = evidence_pack.model_dump(
                            mode="json"
                        )
                    replan_pending = required_failure and has_replan_alternative(
                        attempted_capabilities=attempted_evidence_capabilities,
                        history_available=history_service is not None,
                        provider_capabilities=provider_capabilities,
                    )
                    if required_failure and not replan_pending:
                        observations.append(
                            {
                                "action": "required_evidence_unavailable",
                                "instruction": (
                                    "No untried alternative capability remains. Answer any "
                                    "supported part and disclose the unavailable fact."
                                ),
                            }
                        )
                    continue
                if step.action == "insufficient_data":
                    relevant_facts = _relevant_evidence_facts(question, evidence_pack)
                    if (
                        relevant_facts
                        and not _missing_metric_references(observations)
                        and not insufficient_retry_attempted
                        and step_number < self._max_steps
                    ):
                        insufficient_retry_attempted = True
                        observations.append(
                            {
                                "action": "reconsider_insufficient_data",
                                "available_evidence": [
                                    {
                                        "id": fact.id,
                                        "canonical_ref": fact.canonical_ref,
                                        "label": fact.label,
                                    }
                                    for fact in relevant_facts
                                ],
                                "instruction": (
                                    "Relevant current-report evidence is available. Answer the "
                                    "supported part with sections.data_findings, put practical "
                                    "suggestions in sections.general_advice, and disclose only "
                                    "the genuinely unavailable part in sections.missing_information."
                                ),
                            }
                        )
                        continue
                    grounded = self._grounded_fallback(
                        question=question,
                        metrics=metrics,
                        observations=observations,
                        tool_calls=tool_calls,
                        steps=step_number,
                        reason="model declared data insufficient despite available report evidence",
                        failure_stage="data_availability",
                        candidate=step.answer,
                    )
                    if grounded:
                        return finish(grounded)
                    return finish(self._insufficient_data(
                        metrics=metrics,
                        tool_calls=tool_calls,
                        steps=step_number,
                        missing_metrics=_missing_metric_references(observations),
                        missing_evidence=_missing_evidence_for_question(
                            question,
                            provider_capabilities=provider_capabilities,
                            history_available=history_service is not None,
                        ),
                        candidate=step.answer,
                    ))
                if step.action == "answer":
                    if step.sections is not None:
                        validation = validate_answer_sections(
                            step.sections, evidence_pack
                        )
                        _merge_validated_claims(
                            accepted_claims, validation.valid_claims
                        )
                        if not repair_attempted:
                            _merge_unique_strings(
                                accepted_general_advice, validation.general_advice
                            )
                            _merge_unique_strings(
                                accepted_missing_information,
                                validation.missing_information,
                            )
                        if validation.invalid_claims:
                            last_answer_error = "; ".join(
                                claim.reason for claim in validation.invalid_claims
                            )
                            last_candidate = _step_candidate(step)
                            if not repair_attempted and step_number < self._max_steps:
                                repair_attempted = True
                                observations.append(
                                    {
                                        "action": "repair_answer_claims",
                                        "accepted_answer": {
                                            "valid_claims": [
                                                {
                                                    "text": claim.text,
                                                    "evidence_refs": list(
                                                        claim.evidence_refs
                                                    ),
                                                }
                                                for claim in accepted_claims
                                            ],
                                            "general_advice": list(
                                                accepted_general_advice
                                            ),
                                            "missing_information": list(
                                                accepted_missing_information
                                            ),
                                        },
                                        "invalid_claims": [
                                            {
                                                "text": claim.text,
                                                "evidence_ids": list(
                                                    claim.evidence_ids
                                                ),
                                                "reason": claim.reason,
                                            }
                                            for claim in validation.invalid_claims
                                        ],
                                        "instruction": (
                                            "Repair only invalid claims using evidence IDs from "
                                            "evidence_pack. Do not repeat accepted content."
                                        ),
                                    }
                                )
                                continue
                            if _has_structured_content(
                                accepted_claims,
                                accepted_general_advice,
                                accepted_missing_information,
                            ):
                                return finish(_structured_answer_payload(
                                    valid_claims=accepted_claims,
                                    general_advice=accepted_general_advice,
                                    missing_information=accepted_missing_information,
                                    confidence=step.confidence,
                                    steps=step_number,
                                    tool_calls=tool_calls,
                                    quality="partial",
                                    repair_attempted=repair_attempted,
                                    invalid_claim_count=len(
                                        validation.invalid_claims
                                    ),
                                ))
                            continue
                        return finish(_structured_answer_payload(
                            valid_claims=accepted_claims,
                            general_advice=accepted_general_advice,
                            missing_information=accepted_missing_information,
                            confidence=step.confidence,
                            steps=step_number,
                            tool_calls=tool_calls,
                            quality="repaired" if repair_attempted else "complete",
                            repair_attempted=repair_attempted,
                        ))
                    references = [
                        _canonical_reference(reference)
                        for reference in step.evidence_refs
                    ]
                    try:
                        self._validate_answer(
                            step,
                            references,
                            metrics,
                            summary,
                            evidence,
                            actions,
                            risks,
                            history_service,
                            question,
                        )
                    except ValueError as error:
                        last_answer_error = str(error)
                        last_candidate = _step_candidate(step)
                        observations.append(
                            {
                                "action": "answer",
                                "error": {
                                    "code": "answer_validation",
                                    "message": str(error),
                                    "instruction": "Correct the answer and cite an exact available reference.",
                                },
                            }
                        )
                        continue
                    return finish({
                        "answer": step.answer,
                        "evidence_refs": references,
                        "confidence": step.confidence,
                        "mode": "llm",
                        "steps": step_number,
                        "tool_calls": tool_calls,
                        "prompt_version": PROMPT_VERSION,
                    })
                raw_arguments = step.arguments.model_dump(exclude_none=True)
                normalized_arguments = raw_arguments
                try:
                    normalized_arguments = _normalize_tool_arguments(
                        step.tool_name, raw_arguments
                    )
                    call_key = _tool_call_key(step.tool_name, normalized_arguments)
                    if call_key in successful_tool_results:
                        observations.append(
                            {
                                "tool": step.tool_name,
                                "arguments": normalized_arguments,
                                "error": {
                                    "code": "duplicate_tool_call",
                                    "message": "This successful tool call was already completed.",
                                    "prior_result": successful_tool_results[call_key],
                                    "instruction": "Answer now from the prior result.",
                                },
                            }
                        )
                        grounded = self._grounded_fallback(
                            question=question,
                            metrics=metrics,
                            observations=observations,
                            tool_calls=tool_calls,
                            steps=step_number,
                            reason="model repeated a successful tool call",
                            failure_stage="no_progress",
                            candidate=_step_candidate(step),
                        )
                        if grounded:
                            return finish(grounded)
                        continue
                    tool_calls.append(
                        {"tool": step.tool_name, "arguments": normalized_arguments}
                    )
                    observation = self._execute_tool(
                        step.tool_name,
                        normalized_arguments,
                        summary,
                        metrics,
                        evidence,
                        actions,
                        risks,
                        history_service,
                    )
                except RecoverableToolError as error:
                    last_recoverable_error = error
                    last_candidate = _step_candidate(step)
                    observations.append(
                        {
                            "tool": step.tool_name,
                            "arguments": normalized_arguments,
                            "error": {
                                "code": error.code,
                                "message": str(error),
                                "requested_reference": error.reference,
                                "instruction": (
                                    "Use an exact path from metric_catalog, or choose "
                                    "action=insufficient_data when the required metric is absent."
                                ),
                            },
                        }
                    )
                    continue
                observations.append(
                    {
                        "tool": step.tool_name,
                        "arguments": normalized_arguments,
                        "result": observation,
                    }
                )
                successful_tool_results[call_key] = observation
            except LlmOutputError as error:
                if error.metadata:
                    llm_calls.append(error.metadata)
                if (
                    error.error_code in {"invalid_json", "schema_validation"}
                    and not output_repair_attempted
                    and step_number < self._max_steps
                    and budget_tracker.reserve("repairs")
                ):
                    output_repair_attempted = True
                    output_repair_count += 1
                    observations.append(
                        {
                            "action": "repair_model_output",
                            "error": {
                                "code": error.error_code,
                                "message": str(error),
                            },
                            "candidate": error.candidate_content,
                            "instruction": (
                                "Return one concise JSON object matching the supplied schema. "
                                "Preserve the intended action and evidence plan; use schema "
                                "defaults instead of null for container fields."
                            ),
                        }
                    )
                    continue
                return finish(self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    candidate=error.candidate_content,
                    failure_stage=error.error_code,
                ))
            except ValueError as error:
                return finish(self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    candidate=_step_candidate(step),
                    failure_stage="answer_validation",
                ))
            except LlmError as error:
                if error.metadata:
                    llm_calls.append(error.metadata)
                grounded = self._grounded_fallback(
                    question=question,
                    metrics=metrics,
                    observations=observations,
                    tool_calls=tool_calls,
                    steps=step_number,
                    reason=str(error),
                    failure_stage="model_request",
                )
                if grounded:
                    return finish(grounded)
                return finish(self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    failure_stage="model_request",
                ))
        if last_recoverable_error and last_recoverable_error.code == "metric_not_found":
            return finish(self._insufficient_data(
                metrics=metrics,
                tool_calls=tool_calls,
                steps=self._max_steps,
                missing_metrics=[last_recoverable_error.reference]
                if last_recoverable_error.reference
                else [],
                candidate=last_candidate,
            ))
        if last_answer_error:
            return finish(self._fallback(
                summary,
                evidence,
                last_answer_error,
                tool_calls,
                candidate=last_candidate,
                failure_stage="answer_validation",
            ))
        grounded = self._grounded_fallback(
            question=question,
            metrics=metrics,
            observations=observations,
            tool_calls=tool_calls,
            steps=self._max_steps,
            reason="maximum follow-up steps reached",
            failure_stage="step_limit",
            candidate=last_candidate,
        )
        if grounded:
            return finish(grounded)
        return finish(self._fallback(
            summary,
            evidence,
            "maximum follow-up steps reached",
            tool_calls,
            candidate=last_candidate,
            failure_stage="step_limit",
        ))

    def _execute_tool(
        self,
        name: str | None,
        arguments: dict[str, Any],
        summary: str,
        metrics: dict[str, Any],
        evidence: list[str],
        actions: list[str],
        risks: list[str],
        history_service: MetricHistoryService | None,
    ) -> Any:
        if name == "list_metric_sections":
            return [key for key in metrics if not key.startswith("_")]
        if name == "list_metric_paths":
            return _metric_catalog(metrics)
        if name == "read_report_summary":
            return {"summary": summary, "evidence": evidence, "actions": actions, "risks": risks}
        if name == "read_metric_history":
            path = arguments.get("path")
            if history_service is None:
                raise RecoverableToolError(
                    "metric history is unavailable for this report",
                    code="history_unavailable",
                )
            if not isinstance(path, str) or not path.startswith("metrics."):
                raise RecoverableToolError(
                    "read_metric_history requires a metrics.* path",
                    code="invalid_tool_arguments",
                )
            return history_service.read(path)
        if name == "read_metric":
            path = arguments.get("path")
            if not isinstance(path, str) or not path.startswith("metrics."):
                raise RecoverableToolError(
                    "read_metric requires a metrics.* path",
                    code="invalid_tool_arguments",
                )
            return _resolve_metric(metrics, path)
        raise ValueError(f"follow-up tool is not allowed: {name}")

    def _validate_answer(
        self,
        step: FollowupStep,
        references: list[str],
        metrics: dict[str, Any],
        summary: str,
        evidence: list[str],
        actions: list[str],
        risks: list[str],
        history_service: MetricHistoryService | None,
        question: str,
    ) -> None:
        if not step.answer or not references:
            raise ValueError("follow-up answer is missing text or evidence")
        report = {
            "summary": summary,
            "evidence": evidence,
            "actions": actions,
            "risks": risks,
        }
        evidence_values = [
            _resolve_reference(metrics, report, reference, history_service)
            for reference in references
        ]
        unsupported = unsupported_number(step.answer, evidence_values)
        if unsupported:
            raise ValueError(
                f"answer contains unsupported number: {unsupported.rstrip('%')}"
            )
        required_reference = required_reference_for_question(question, metrics)
        if required_reference and required_reference not in references:
            raise ValueError(
                f"answer to this question must cite {required_reference}"
            )
        targets = metrics.get("_targets")
        target_reference = f"targets.{required_reference}" if required_reference else None
        if (
            target_reference
            and isinstance(targets, dict)
            and required_reference in targets
            and question_requests_normative_comparison(question)
            and target_reference not in references
        ):
            raise ValueError(
                f"answer comparing against the merchant target must cite {target_reference}"
            )
        normative_text = f"{question} {step.answer}"
        if answer_requires_benchmark_disclaimer(
            normative_text, references, metrics
        ):
            benchmark_disclaimer = step.answer or ""
            if "基准" not in benchmark_disclaimer or not any(
                marker in benchmark_disclaimer
                for marker in ("没有", "缺少", "缺乏", "无法", "不能", "未提供")
            ):
                raise ValueError(
                    "answer must state that no saved benchmark supports the normative claim"
                )

    def _fallback(
        self,
        summary: str,
        evidence: list[str],
        reason: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        candidate: str | None = None,
        failure_stage: str = "configuration",
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
            "failure_detail": {
                "stage": failure_stage,
                "reason": reason,
            },
            "prompt_version": PROMPT_VERSION,
        }

    def _insufficient_data(
        self,
        *,
        metrics: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        steps: int,
        missing_metrics: list[str | None],
        missing_evidence: list[str] | None = None,
        candidate: str | None = None,
    ) -> dict[str, Any]:
        missing = [item for item in missing_metrics if item]
        unavailable_evidence = list(missing_evidence or [])
        sections = [key for key in metrics if not key.startswith("_")]
        if unavailable_evidence:
            labels = {
                "metric_history": "历史经营报告",
                "external_industry_context": "行业与城市知识",
                "location_competitors": "周边竞品快照",
            }
            missing_labels = "、".join(
                labels[item] for item in unavailable_evidence
            )
            reason = f"当前项目尚未保存回答该问题所需的外部证据：{missing_labels}。"
            guidance = (
                "请先运行商圈/选址分析生成竞品快照后再追问。"
                if "location_competitors" in unavailable_evidence
                else "请先生成或接入相应证据后再追问。"
            )
            failure_stage = "evidence_availability"
        else:
            requested = f"（{', '.join(missing)}）" if missing else ""
            reason = f"当前保存的报告未包含回答该问题所需的指标{requested}。"
            guidance = (
                "这通常表示生成报告时未运行相应分析工具；"
                "请重新生成包含该指标的报告后再追问。"
            )
            failure_stage = "data_availability"
        return {
            "answer": f"{reason}{guidance}",
            "evidence_refs": [],
            "confidence": 1.0,
            "mode": "insufficient_data",
            "steps": steps,
            "tool_calls": tool_calls,
            "fallback_reason": reason,
            "missing_metrics": missing,
            "missing_evidence": unavailable_evidence,
            "available_sections": sections,
            "failure_detail": {
                "stage": failure_stage,
                "reason": reason,
            },
            "prompt_version": PROMPT_VERSION,
        }

    def _grounded_fallback(
        self,
        *,
        question: str,
        metrics: dict[str, Any],
        observations: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        steps: int,
        reason: str,
        failure_stage: str,
        candidate: str | None = None,
    ) -> dict[str, Any] | None:
        deterministic = _deterministic_metric_answer(question, metrics)
        if deterministic is not None:
            answer, references = deterministic
        else:
            observed = _observed_metric_values(observations)
            if not observed:
                return None
            references = [path for path, _ in observed]
            values = "；".join(
                f"{_metric_label(path)}为{_format_metric_value(path, value)}"
                for path, value in observed
            )
            answer = (
                f"根据已经成功读取的报告指标，{values}。"
                "模型未在限定轮次内形成进一步解释，因此不补充未经指标支持的原因判断。"
            )
        return {
            "answer": answer,
            "evidence_refs": references,
            "confidence": 0.85,
            "mode": "deterministic",
            "steps": steps,
            "tool_calls": tool_calls,
            "fallback_reason": reason,
            "supporting_evidence": [
                f"{_metric_label(path)}：{_format_metric_value(path, _resolve_metric(metrics, path))}"
                for path in references[:6]
            ],
            "failure_detail": {
                "stage": failure_stage,
                "reason": reason,
            },
            "prompt_version": PROMPT_VERSION,
        }


def _structured_answer_payload(
    *,
    valid_claims: list[ValidatedClaim],
    general_advice: list[str],
    missing_information: list[str],
    confidence: float,
    steps: int,
    tool_calls: list[dict[str, Any]],
    quality: str,
    repair_attempted: bool,
    invalid_claim_count: int = 0,
) -> dict[str, Any]:
    data_findings = []
    for claim in valid_claims:
        finding = {"text": claim.text, "evidence_refs": list(claim.evidence_refs)}
        scope = _claim_scope(claim.evidence_refs)
        if scope != "current_report":
            finding["scope"] = scope
        data_findings.append(finding)
    sections = {
        "data_findings": data_findings,
        "general_advice": list(general_advice),
        "missing_information": list(missing_information),
    }
    rendered: list[str] = []
    finding_groups = {
        scope: [
            item["text"]
            for item in data_findings
            if item.get("scope", "current_report") == scope
        ]
        for scope in (
            "current_report",
            "external",
            "history",
            "reference",
            "mixed",
        )
    }
    for title, values in (
        ("基于门店数据", finding_groups["current_report"]),
        ("外部行业证据", finding_groups["external"]),
        ("历史经营数据", finding_groups["history"]),
        ("目标与参考基准", finding_groups["reference"]),
        ("综合证据", finding_groups["mixed"]),
        ("通用经营建议", sections["general_advice"]),
        ("当前缺少的信息", sections["missing_information"]),
    ):
        if values:
            rendered.append(f"{title}：" + "；".join(values))
    return {
        "answer": "\n\n".join(rendered),
        "sections": sections,
        "evidence_refs": _claim_evidence_refs(valid_claims),
        "confidence": confidence,
        "quality": quality,
        "mode": "llm",
        "steps": steps,
        "tool_calls": tool_calls,
        "claim_validation": {
            "valid_claim_count": len(valid_claims),
            "invalid_claim_count": invalid_claim_count,
            "repair_attempted": repair_attempted,
        },
        "prompt_version": PROMPT_VERSION,
    }


def _claim_scope(evidence_refs: tuple[str, ...]) -> str:
    scopes = set()
    for reference in evidence_refs:
        if reference.startswith("external."):
            scopes.add("external")
        elif reference.startswith("history."):
            scopes.add("history")
        elif reference.startswith(("targets.", "benchmarks.")):
            scopes.add("reference")
        else:
            scopes.add("current_report")
    return next(iter(scopes)) if len(scopes) == 1 else "mixed"


def _merge_validated_claims(
    target: list[ValidatedClaim], additions: tuple[ValidatedClaim, ...]
) -> None:
    seen = {(claim.text, claim.evidence_refs) for claim in target}
    for claim in additions:
        if len(target) >= 5:
            break
        key = (claim.text, claim.evidence_refs)
        if key not in seen:
            target.append(claim)
            seen.add(key)


def _merge_unique_strings(target: list[str], additions: tuple[str, ...]) -> None:
    seen = set(target)
    for value in additions:
        if len(target) >= 4:
            break
        if value not in seen:
            target.append(value)
            seen.add(value)


def _compact_metric_catalog(
    catalog: list[dict[str, Any]], limit: int = 80
) -> list[dict[str, Any]]:
    return [
        {
            key: item[key]
            for key in ("ref", "label", "value_type", "unit")
            if item.get(key) not in (None, "")
        }
        for item in catalog[:limit]
    ]


def _has_structured_content(
    valid_claims: list[ValidatedClaim],
    general_advice: list[str],
    missing_information: list[str],
) -> bool:
    return bool(valid_claims or general_advice or missing_information)


def _claim_evidence_refs(valid_claims: list[ValidatedClaim]) -> list[str]:
    references: dict[str, None] = {}
    for claim in valid_claims:
        for reference in claim.evidence_refs:
            references.setdefault(reference, None)
    return list(references)


def _relevant_evidence_facts(
    question: str, evidence_pack: EvidencePack, limit: int = 20
) -> list[Any]:
    sections = registry_relevant_sections(question)
    if not sections:
        return []
    prefixes = tuple(f"metrics.{section}." for section in sections)
    return [
        fact
        for fact in evidence_pack.facts
        if fact.canonical_ref.startswith(prefixes)
    ][:limit]


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
            raise MetricNotFoundError(reference)
    return current


def _resolve_reference(
    metrics: dict[str, Any],
    report: dict[str, Any],
    reference: str,
    history_service: MetricHistoryService | None = None,
) -> Any:
    if reference.startswith("metrics."):
        return _resolve_metric(metrics, reference)
    if reference.startswith("targets.metrics."):
        targets = metrics.get("_targets")
        metric_reference = reference.removeprefix("targets.")
        if isinstance(targets, dict) and metric_reference in targets:
            return targets[metric_reference]
        raise ValueError(f"unknown target reference: {reference}")
    if reference.startswith("history.analysis."):
        if history_service is None:
            raise ValueError("metric history is unavailable")
        return history_service.resolve(reference)
    if not reference.startswith("report."):
        raise ValueError(f"invalid evidence reference: {reference}")
    current: Any = report
    for part in reference.removeprefix("report.").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"unknown evidence reference: {reference}")
    return current


def _canonical_reference(reference: str) -> str:
    if reference == "read_report_summary":
        return "report.summary"
    return reference


def _normalize_tool_arguments(
    tool_name: str | None, arguments: dict[str, Any]
) -> dict[str, Any]:
    if tool_name not in {"read_metric", "read_metric_history"}:
        return {}
    raw_path = next(
        (
            arguments.get(key)
            for key in ("path", "field", "metric", "reference")
            if arguments.get(key) is not None
        ),
        None,
    )
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise RecoverableToolError(
            "read_metric requires a path, field, metric, or reference string",
            code="invalid_tool_arguments",
        )
    path = raw_path.strip()
    if not path.startswith("metrics."):
        path = f"metrics.{path}"
    aliases = {
        "metrics.revenue.delivery_share": "metrics.channels.delivery_revenue_share",
        "metrics.channels.delivery_share": "metrics.channels.delivery_revenue_share",
    }
    return {"path": aliases.get(path, path)}


def _enrich_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(metrics)
    original_channels = metrics.get("channels")
    if not isinstance(original_channels, dict):
        return enriched
    channels = dict(original_channels)
    enriched["channels"] = channels
    rows = channels.get("channels")
    delivery_rows = (
        [row for row in rows if isinstance(row, dict) and row.get("channel_type") == "delivery"]
        if isinstance(rows, list)
        else []
    )

    def row_sum(field: str) -> float:
        return round(
            sum(_number(row.get(field)) or 0.0 for row in delivery_rows), 2
        )

    if delivery_rows:
        channels.setdefault("delivery_food_cost", row_sum("food_cost"))
        channels.setdefault("delivery_platform_fee", row_sum("platform_fee"))
        channels.setdefault("delivery_packaging_cost", row_sum("packaging_cost"))
    delivery_revenue = _number(channels.get("delivery_revenue"))
    delivery_profit = _number(channels.get("delivery_contribution_profit"))
    if (
        "delivery_contribution_margin" not in channels
        and delivery_revenue
        and delivery_profit is not None
    ):
        channels["delivery_contribution_margin"] = round(
            delivery_profit / delivery_revenue, 4
        )
    revenue_metrics = metrics.get("revenue")
    total_revenue = (
        _number(revenue_metrics.get("total_revenue"))
        if isinstance(revenue_metrics, dict)
        else None
    )
    if (
        "delivery_revenue_share" not in channels
        and total_revenue
        and delivery_revenue is not None
    ):
        channels["delivery_revenue_share"] = round(
            delivery_revenue / total_revenue, 4
        )
    return enriched


def _metric_catalog(metrics: dict[str, Any], limit: int = 200) -> list[dict[str, str]]:
    return registry_metric_catalog(metrics, limit=limit)  # type: ignore[return-value]


def _metric_snapshot(
    metrics: dict[str, Any], *, question: str = "", limit: int = 120
) -> list[dict[str, Any]]:
    return registry_metric_snapshot(metrics, question=question, limit=limit)


def _relevant_metric_sections(question: str) -> set[str]:
    return registry_relevant_sections(question)


def _tool_call_key(tool_name: str | None, arguments: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"


def _deterministic_metric_answer(
    question: str, metrics: dict[str, Any]
) -> tuple[str, list[str]] | None:
    if not any(keyword in question for keyword in ("外卖", "配送", "美团", "饿了么")):
        return None
    channels = metrics.get("channels")
    if not isinstance(channels, dict):
        return None
    revenue = _number(channels.get("delivery_revenue"))
    share = _number(channels.get("delivery_revenue_share"))
    contribution = _number(channels.get("delivery_contribution_profit"))
    commission_rate = _number(channels.get("delivery_commission_rate"))
    packaging_per_order = _number(channels.get("delivery_packaging_per_order"))
    contribution_margin = _number(channels.get("delivery_contribution_margin"))
    if contribution_margin is None and revenue and contribution is not None:
        contribution_margin = contribution / revenue

    if any(keyword in question for keyword in ("贡献", "利润", "赚", "偏低", "为什么")):
        if revenue is None or contribution is None:
            return None
        margin_text = (
            f"，贡献率为{contribution_margin * 100:.2f}%" if contribution_margin is not None else ""
        )
        share_text = f"，占总营收{share * 100:.2f}%" if share is not None else ""
        commission_text = (
            f"平台佣金率按{commission_rate * 100:.1f}%计算"
            if commission_rate is not None
            else "报告未保存平台佣金率"
        )
        packaging_text = (
            f"，另计每单包材{packaging_per_order:.2f}元"
            if packaging_per_order is not None
            else ""
        )
        answer = (
            f"样本外卖营收为{revenue:.2f}元{share_text}；扣除食材、平台佣金和包材后，"
            f"贡献利润为{contribution:.2f}元{margin_text}。{commission_text}{packaging_text}。"
            "因此利润会被食材成本、佣金和包材共同压缩；但当前报告没有目标值或同行基准，"
            "只能解释利润构成，不能仅凭该样本断言贡献率一定偏低。该贡献利润尚未分摊房租和人工等固定成本。"
        )
        references = [
            f"metrics.channels.{field}"
            for field in (
                "delivery_revenue",
                "delivery_revenue_share",
                "delivery_contribution_profit",
                "delivery_contribution_margin",
                "delivery_commission_rate",
                "delivery_packaging_per_order",
                "channels",
            )
            if field in channels
        ]
        return answer, references

    if share is not None:
        return (
            f"样本外卖营收占总营收的{share * 100:.2f}%"
            + (f"，对应外卖营收{revenue:.2f}元。" if revenue is not None else "。"),
            [
                "metrics.channels.delivery_revenue_share",
                *(
                    ["metrics.channels.delivery_revenue"]
                    if revenue is not None
                    else []
                ),
            ],
        )
    return None


def _observed_metric_values(
    observations: list[dict[str, Any]], limit: int = 6
) -> list[tuple[str, Any]]:
    observed: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        arguments = observation.get("arguments")
        path = arguments.get("path") if isinstance(arguments, dict) else None
        if (
            isinstance(path, str)
            and "result" in observation
            and path not in seen
            and not isinstance(observation["result"], (dict, list))
        ):
            observed.append((path, observation["result"]))
            seen.add(path)
            if len(observed) >= limit:
                break
    return observed


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_label(path: str) -> str:
    return registry_metric_label(path)


def _format_metric_value(path: str, value: Any) -> str:
    return registry_format_value(path, value)


def _missing_metric_references(observations: list[dict[str, Any]]) -> list[str]:
    references: list[str] = []
    for observation in observations:
        error = observation.get("error")
        if not isinstance(error, dict) or error.get("code") != "metric_not_found":
            continue
        reference = error.get("requested_reference")
        if isinstance(reference, str) and reference not in references:
            references.append(reference)
    return references


def _missing_evidence_for_question(
    question: str,
    *,
    provider_capabilities: set[str],
    history_available: bool,
) -> list[str]:
    missing: list[str] = []
    requirements = (
        (
            "location_competitors",
            ("附近", "周边", "商圈", "竞品", "竞争对手", "公里"),
            "location_competitors" in provider_capabilities,
        ),
        (
            "external_industry_context",
            ("行业", "市场", "趋势", "当地", "本地", "成都"),
            "external_industry_context" in provider_capabilities,
        ),
        (
            "metric_history",
            ("上次", "上期", "之前", "历史", "相比", "变化"),
            history_available,
        ),
    )
    for capability, keywords, available in requirements:
        if not available and any(keyword in question for keyword in keywords):
            missing.append(capability)
    return missing


def _report_context(
    summary: str,
    evidence: list[str],
    actions: list[str],
    risks: list[str],
) -> dict[str, object]:
    return {
        "summary": {"ref": "report.summary", "value": summary},
        "evidence": [
            {"ref": f"report.evidence.{index}", "value": value}
            for index, value in enumerate(evidence)
        ],
        "actions": [
            {"ref": f"report.actions.{index}", "value": value}
            for index, value in enumerate(actions)
        ],
        "risks": [
            {"ref": f"report.risks.{index}", "value": value}
            for index, value in enumerate(risks)
        ],
    }


def _step_candidate(step: FollowupStep | None) -> str | None:
    if step is None:
        return None
    if step.answer:
        return step.answer[:4000]
    return json.dumps(step.model_dump(), ensure_ascii=False)[:4000]
