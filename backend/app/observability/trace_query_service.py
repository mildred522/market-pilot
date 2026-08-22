from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentExecutionTrace, AnalysisResult, AnalysisRun
from app.observability.contracts import (
    AgentRunDetail,
    AgentRunBudgetView,
    AgentRunStage,
    AgentRunSummary,
    AgentRunUsage,
    AgentRunVerification,
    PublicPlan,
)


class AgentRunNotFoundError(LookupError):
    pass


class AgentRunQueryService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_analysis(self, analysis_id: int) -> list[AgentRunSummary]:
        analysis = self._require_analysis(analysis_id)
        rows = self._db.scalars(
            select(AgentExecutionTrace)
            .where(
                AgentExecutionTrace.analysis_id == analysis.id,
                AgentExecutionTrace.project_id == analysis.project_id,
            )
            .order_by(AgentExecutionTrace.created_at.asc(), AgentExecutionTrace.id.asc())
        ).all()
        return [self._summary(row) for row in rows]

    def get_for_analysis(self, analysis_id: int, request_id: str) -> AgentRunDetail:
        analysis = self._require_analysis(analysis_id)
        row = self._db.scalar(
            select(AgentExecutionTrace).where(
                AgentExecutionTrace.request_id == request_id,
                AgentExecutionTrace.analysis_id == analysis.id,
                AgentExecutionTrace.project_id == analysis.project_id,
            )
        )
        if row is None:
            raise AgentRunNotFoundError("agent run not found")
        return self._detail(row)

    def _require_analysis(self, analysis_id: int) -> AnalysisResult:
        analysis = self._db.get(AnalysisResult, analysis_id)
        if analysis is None:
            raise AgentRunNotFoundError("analysis not found")
        return analysis

    def _summary(self, row: AgentExecutionTrace) -> AgentRunSummary:
        payload = _payload(row)
        return AgentRunSummary(
            request_id=row.request_id,
            project_id=row.project_id,
            analysis_id=int(row.analysis_id),
            run_id=row.run_id,
            operation=_operation(row.operation),
            status=self._run_status(row, payload),
            created_at=row.created_at,
            duration_ms=_nonnegative_int(payload.get("duration_ms")),
            usage=_usage(payload),
        )

    def _run_status(
        self, row: AgentExecutionTrace, payload: dict[str, Any]
    ) -> str:
        if payload.get("status") in {"completed", "degraded", "failed"}:
            return str(payload["status"])
        run = self._db.get(AnalysisRun, row.run_id) if row.run_id is not None else None
        if run is not None and run.status in {"completed", "degraded", "failed"}:
            return run.status
        return "degraded" if _string_list(payload.get("fallback_reasons")) else "completed"

    def _detail(self, row: AgentExecutionTrace) -> AgentRunDetail:
        payload = _payload(row)
        summary = self._summary(row)
        failures = _string_list(payload.get("verification_failures"))
        return AgentRunDetail(
            **summary.model_dump(),
            initial_plan=_plan(payload.get("initial_plan")),
            revised_plan=(
                _plan(payload.get("revised_plan"))
                if isinstance(payload.get("revised_plan"), dict)
                else None
            ),
            timeline=_timeline(payload),
            verification=AgentRunVerification(
                failure_count=len(failures),
                passed=not failures,
            ),
            fallback_reasons=_string_list(payload.get("fallback_reasons")),
            selected_memory_count=len(_integer_list(payload.get("selected_memory_ids"))),
            budget=_budget(payload.get("budget")),
            planning_disclosure=_planning_disclosure(
                payload.get("planning_disclosure")
            ),
        )


def _payload(row: AgentExecutionTrace) -> dict[str, Any]:
    return row.trace_json if isinstance(row.trace_json, dict) else {}


def _usage(payload: dict[str, Any]) -> AgentRunUsage:
    calls = _dict_list(payload.get("llm_calls"))
    return AgentRunUsage(
        model_calls=len(calls),
        tool_calls=len(_dict_list(payload.get("tool_executions"))),
        replan_count=_nonnegative_int(payload.get("replan_count")),
        output_repair_count=_nonnegative_int(payload.get("output_repair_count")),
        input_tokens=_sum_optional(calls, "input_tokens"),
        output_tokens=_sum_optional(calls, "output_tokens"),
        total_tokens=_sum_optional(calls, "total_tokens"),
        token_usage_complete=bool(calls)
        and all(isinstance(call.get("total_tokens"), int) for call in calls),
    )


def _budget(value: Any) -> AgentRunBudgetView:
    source = value if isinstance(value, dict) else {}
    limits = source.get("limits") if isinstance(source.get("limits"), dict) else {}
    used = source.get("used") if isinstance(source.get("used"), dict) else {}
    return AgentRunBudgetView(
        limits={key: max(0, item) for key, item in limits.items() if isinstance(item, int)},
        used={key: max(0, item) for key, item in used.items() if isinstance(item, int)},
        exhausted_dimensions=_string_list(source.get("exhausted_dimensions"))[:6],
        evidence_truncated=bool(source.get("evidence_truncated", False)),
    )


def _timeline(payload: dict[str, Any]) -> list[AgentRunStage]:
    stages = [
        AgentRunStage(
            stage="plan",
            label="生成执行计划",
            status="completed",
            public_detail=_plan_detail(payload.get("initial_plan")),
        )
    ]
    for call in _dict_list(payload.get("llm_calls")):
        stages.append(
            AgentRunStage(
                stage="model",
                label=_role_label(str(call.get("role", "unspecified"))),
                status=_status(call.get("status")),
                duration_ms=_optional_nonnegative_int(call.get("duration_ms")),
                public_detail="结构化模型调用",
                role=str(call.get("role", "unspecified"))[:80],
                model=_optional_text(call.get("model"), 120),
                input_tokens=_optional_nonnegative_int(call.get("input_tokens")),
                output_tokens=_optional_nonnegative_int(call.get("output_tokens")),
                total_tokens=_optional_nonnegative_int(call.get("total_tokens")),
                retry_count=_optional_nonnegative_int(call.get("retry_count")),
                error_code=_optional_text(call.get("error_code"), 80),
            )
        )
    for tool in _dict_list(payload.get("tool_executions")):
        stages.append(
            AgentRunStage(
                stage="tool",
                label=f"执行工具：{str(tool.get('tool_name', 'unknown'))[:80]}",
                status=_status(tool.get("status")),
                duration_ms=_optional_nonnegative_int(tool.get("duration_ms")),
                public_detail="确定性业务分析工具",
                error_code=_optional_text(tool.get("error_code"), 80),
            )
        )
    for event in _dict_list(payload.get("evidence_events")):
        count = _nonnegative_int(event.get("evidence_count"))
        stages.append(
            AgentRunStage(
                stage="retrieve",
                label=f"获取证据：{str(event.get('capability', 'external'))[:80]}",
                status=_status(event.get("status")),
                public_detail=f"返回 {count} 条证据",
                error_code=_optional_text(event.get("error_code"), 80),
            )
        )
    if isinstance(payload.get("revised_plan"), dict):
        stages.append(
            AgentRunStage(
                stage="replan",
                label="调整执行计划",
                status="completed",
                public_detail=_plan_detail(payload.get("revised_plan")),
            )
        )
    failures = _string_list(payload.get("verification_failures"))
    stages.append(
        AgentRunStage(
            stage="verify",
            label="校验回答证据",
            status="degraded" if failures else "completed",
            public_detail=f"发现 {len(failures)} 项校验问题",
        )
    )
    if _string_list(payload.get("fallback_reasons")):
        stages.append(
            AgentRunStage(
                stage="fallback",
                label="执行降级策略",
                status="degraded",
                public_detail="保留可验证内容并说明能力边界",
            )
        )
    return stages


def _plan(value: Any) -> PublicPlan:
    source = value if isinstance(value, dict) else {}
    return PublicPlan(
        intent=str(source.get("intent", ""))[:80],
        goal=str(source.get("goal", ""))[:300],
        workflow=_optional_text(source.get("workflow"), 80),
        dimensions=_string_list(source.get("dimensions"))[:6],
        tools=_string_list(source.get("tools"))[:8],
        missing_inputs=_string_list(source.get("missing_inputs"))[:10],
        requires_external_api=bool(source.get("requires_external_api", False)),
    )


def _plan_detail(value: Any) -> str:
    plan = _plan(value)
    if plan.workflow:
        return f"选择工作流 {plan.workflow}，展开 {len(plan.tools)} 个工具"
    if plan.tools:
        return f"选择 {len(plan.tools)} 个工具"
    return "无需确定性分析工具"


def _planning_disclosure(value: Any) -> dict[str, int | float]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, int | float] = {}
    for key in (
        "candidate_workflow_count",
        "catalog_characters",
        "legacy_catalog_characters",
        "reduction_percent",
    ):
        item = source.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            result[key] = max(0, item)
    return result


def _status(value: Any) -> str:
    return str(value) if value in {"completed", "degraded", "failed"} else "failed"


def _operation(value: str) -> str:
    return value if value in {"operating_analysis", "followup"} else "followup"


def _sum_optional(calls: list[dict[str, Any]], key: str) -> int | None:
    values = [call.get(key) for call in calls if isinstance(call.get(key), int)]
    return sum(values) if values else None


def _nonnegative_int(value: Any) -> int:
    return max(0, value) if isinstance(value, int) else 0


def _optional_nonnegative_int(value: Any) -> int | None:
    return _nonnegative_int(value) if isinstance(value, int) else None


def _optional_text(value: Any, maximum: int) -> str | None:
    return str(value)[:maximum] if value not in {None, ""} else None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item)[:500] for item in value] if isinstance(value, list) else []


def _integer_list(value: Any) -> list[int]:
    return [item for item in value if isinstance(item, int)] if isinstance(value, list) else []


def _role_label(role: str) -> str:
    return {
        "planner": "模型规划",
        "replanner": "模型重新规划",
        "synthesizer": "模型综合报告",
        "followup": "模型生成追问回答",
        "revision_planner": "模型规划回答修订",
        "probe": "模型连接检查",
        "live_eval": "模型实时评测",
    }.get(role, "模型调用")
