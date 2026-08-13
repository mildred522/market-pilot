from __future__ import annotations

import json
from typing import Any

from app.agent_runtime.contracts import FollowupStep
from app.agent_runtime.llm_client import (
    LlmClient,
    LlmError,
    LlmOutputError,
    llm_client_from_environment,
)
from app.agent_runtime.metric_registry import (
    answer_requires_benchmark_disclaimer,
    data_resource_context,
    format_value as registry_format_value,
    metric_catalog as registry_metric_catalog,
    metric_label as registry_metric_label,
    metric_snapshot as registry_metric_snapshot,
    relevant_sections as registry_relevant_sections,
    required_reference_for_question,
)
from app.agent_runtime.prompts import FOLLOWUP_SYSTEM_PROMPT, PROMPT_VERSION


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
    def __init__(self, client: LlmClient | None = None, max_steps: int = 4) -> None:
        self._client = client or llm_client_from_environment()
        self._max_steps = max(1, min(max_steps, 4))

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
        metrics = _enrich_metrics(metrics)
        if not self._client.configured:
            return self._fallback(summary, evidence, "LLM not configured")

        observations: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        successful_tool_results: dict[str, Any] = {}
        metric_catalog = registry_metric_catalog(metrics, question=question)
        last_recoverable_error: RecoverableToolError | None = None
        last_answer_error: str | None = None
        last_candidate: str | None = None
        base_context = {
            "question": question,
            "metric_sections": [key for key in metrics if not key.startswith("_")],
            "metric_catalog": metric_catalog,
            "metric_snapshot": _metric_snapshot(metrics, question=question),
            "data_resources": data_resource_context(metrics, question=question),
            "report": _report_context(summary, evidence, actions, risks),
            "read_only_tools": READ_ONLY_TOOLS,
        }
        for step_number in range(1, self._max_steps + 1):
            step: FollowupStep | None = None
            try:
                step = self._client.generate_json(
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
                if step.action == "insufficient_data":
                    return self._insufficient_data(
                        metrics=metrics,
                        tool_calls=tool_calls,
                        steps=step_number,
                        missing_metrics=_missing_metric_references(observations),
                        candidate=step.answer,
                    )
                if step.action == "answer":
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
                    return {
                        "answer": step.answer,
                        "evidence_refs": references,
                        "confidence": step.confidence,
                        "mode": "llm",
                        "steps": step_number,
                        "tool_calls": tool_calls,
                        "prompt_version": PROMPT_VERSION,
                    }
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
                            return grounded
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
                return self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    candidate=error.candidate_content,
                    failure_stage=error.error_code,
                )
            except ValueError as error:
                return self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    candidate=_step_candidate(step),
                    failure_stage="answer_validation",
                )
            except LlmError as error:
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
                    return grounded
                return self._fallback(
                    summary,
                    evidence,
                    str(error),
                    tool_calls,
                    failure_stage="model_request",
                )
        if last_recoverable_error and last_recoverable_error.code == "metric_not_found":
            return self._insufficient_data(
                metrics=metrics,
                tool_calls=tool_calls,
                steps=self._max_steps,
                missing_metrics=[last_recoverable_error.reference]
                if last_recoverable_error.reference
                else [],
                candidate=last_candidate,
            )
        if last_answer_error:
            return self._fallback(
                summary,
                evidence,
                last_answer_error,
                tool_calls,
                candidate=last_candidate,
                failure_stage="answer_validation",
            )
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
            return grounded
        return self._fallback(
            summary,
            evidence,
            "maximum follow-up steps reached",
            tool_calls,
            candidate=last_candidate,
            failure_stage="step_limit",
        )

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
        if name == "list_metric_paths":
            return _metric_catalog(metrics)
        if name == "read_report_summary":
            return {"summary": summary, "evidence": evidence, "actions": actions, "risks": risks}
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
        for reference in references:
            _resolve_reference(metrics, report, reference)
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
            and any(marker in question for marker in ("高", "低", "好", "差", "正常", "合理", "达标"))
            and target_reference not in references
        ):
            raise ValueError(
                f"answer comparing against the merchant target must cite {target_reference}"
            )
        if answer_requires_benchmark_disclaimer(question, references, metrics):
            benchmark_disclaimer = step.answer or ""
            if "基准" not in benchmark_disclaimer or not any(
                marker in benchmark_disclaimer
                for marker in ("没有", "缺少", "缺乏", "无法", "不能", "未提供")
            ):
                raise ValueError(
                    "answer must state that no saved benchmark supports calling the metric low"
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
                "candidate": candidate,
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
        candidate: str | None = None,
    ) -> dict[str, Any]:
        missing = [item for item in missing_metrics if item]
        sections = [key for key in metrics if not key.startswith("_")]
        requested = f"（{', '.join(missing)}）" if missing else ""
        reason = f"当前保存的报告未包含回答该问题所需的指标{requested}。"
        return {
            "answer": (
                f"{reason}这通常表示生成报告时未运行相应分析工具；"
                "请重新生成包含该指标的报告后再追问。"
            ),
            "evidence_refs": [],
            "confidence": 1.0,
            "mode": "insufficient_data",
            "steps": steps,
            "tool_calls": tool_calls,
            "fallback_reason": reason,
            "missing_metrics": missing,
            "available_sections": sections,
            "failure_detail": {
                "stage": "data_availability",
                "reason": reason,
                "candidate": candidate,
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
                "candidate": candidate,
            },
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
            raise MetricNotFoundError(reference)
    return current


def _resolve_reference(
    metrics: dict[str, Any], report: dict[str, Any], reference: str
) -> Any:
    if reference.startswith("metrics."):
        return _resolve_metric(metrics, reference)
    if reference.startswith("targets.metrics."):
        targets = metrics.get("_targets")
        metric_reference = reference.removeprefix("targets.")
        if isinstance(targets, dict) and metric_reference in targets:
            return targets[metric_reference]
        raise ValueError(f"unknown target reference: {reference}")
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
    if tool_name != "read_metric":
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
