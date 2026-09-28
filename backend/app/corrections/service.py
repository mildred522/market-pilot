from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import AgentPlan, PlannedTool
from app.agent_runtime.llm_client import DisabledLlmClient
from app.agent_runtime.metric_registry import data_resource_context
from app.agent_runtime.synthesis import synthesize_operating_report
from app.agent_runtime.tools import OperatingToolContext, execute_operating_tools
from app.agents.state import AgentState
from app.corrections.dependencies import CORRECTION_TOOL_DEPENDENCIES
from app.corrections.repository import AnalysisInputSnapshotRepository
from app.db.models import (
    AnalysisResult,
    AnalysisRun,
    CorrectionProposal,
    Project,
    UploadedFile,
    utc_now,
)
from app.memory.project_profile import ProjectProfileService
from app.observability.agent_trace import AgentTraceRecorder
from app.services.csv_ingestion_service import prepare_frame, read_csv_path, validate_and_clean


class CorrectionConflictError(RuntimeError):
    pass


class CorrectionExecutionError(RuntimeError):
    pass


class CorrectionWorkflowService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def apply(self, proposal_id: int, *, idempotency_key: str) -> AnalysisResult:
        started = perf_counter()
        proposal = self._db.get(CorrectionProposal, proposal_id)
        if proposal is None:
            raise LookupError("correction proposal not found")
        if proposal.idempotency_key != idempotency_key:
            raise CorrectionConflictError("idempotency key does not match")
        if proposal.status == "applied" and proposal.applied_analysis_id is not None:
            result = self._db.get(AnalysisResult, proposal.applied_analysis_id)
            if result is None:
                raise CorrectionConflictError("applied analysis is unavailable")
            return result
        if proposal.status != "pending":
            raise CorrectionConflictError("correction proposal is not pending")

        claimed = self._db.execute(
            update(CorrectionProposal)
            .where(
                CorrectionProposal.id == proposal.id,
                CorrectionProposal.status == "pending",
            )
            .values(status="applying", updated_at=utc_now())
        )
        if claimed.rowcount != 1:
            self._db.expire_all()
            current = self._db.get(CorrectionProposal, proposal_id)
            if current is not None and current.status == "applied":
                result = self._db.get(AnalysisResult, current.applied_analysis_id)
                if result is not None:
                    return result
            raise CorrectionConflictError("correction proposal is already being processed")
        proposal.status = "applying"

        source = self._db.get(AnalysisResult, proposal.source_analysis_id)
        snapshot = AnalysisInputSnapshotRepository(self._db).get_for_analysis(
            proposal.source_analysis_id
        )
        if source is None or snapshot is None:
            raise CorrectionConflictError("source analysis input snapshot is unavailable")
        latest = self._db.scalar(
            select(AnalysisResult)
            .where(
                AnalysisResult.project_id == proposal.project_id,
                AnalysisResult.stage == "operating",
            )
            .order_by(AnalysisResult.id.desc())
            .limit(1)
        )
        if latest is None or latest.id != source.id:
            raise CorrectionConflictError("source analysis is stale")

        orders, menu, reviews = self._load_frames(
            snapshot.input_kind, snapshot.sources_json, proposal.project_id
        )
        assumptions = {
            **snapshot.cost_assumptions_json,
            proposal.target_field: proposal.new_value,
        }
        selected_tools = list(CORRECTION_TOOL_DEPENDENCIES[proposal.target_field])
        batch = execute_operating_tools(
            selected_tools,
            OperatingToolContext(
                orders=orders,
                menu=menu,
                reviews=reviews,
                cost_assumptions=assumptions,
            ),
            required_tools=set(selected_tools),
        )
        if batch.status == "failed":
            error = next(
                (item.error_code for item in batch.executions if item.status == "failed"),
                "incremental_recompute_failed",
            )
            raise CorrectionExecutionError(str(error))

        merged_sections = {
            key: value
            for key, value in source.metrics_json.items()
            if not key.startswith("_")
        }
        merged_sections.update(batch.successful_data)
        plan = AgentPlan(
            intent="confirmed_correction",
            goal=f"apply confirmed correction to {proposal.target_field}",
            tools=[
                PlannedTool(name=name, reason="affected by confirmed input correction")
                for name in selected_tools
            ],
        )
        state = AgentState(
            project_id=proposal.project_id,
            question=snapshot.question,
            stage="operating",
            intent=plan.intent,
            plan=[*selected_tools, "generate_recommendations"],
            tool_results=merged_sections,
        )
        state, _, synthesis_fallbacks = synthesize_operating_report(
            client=DisabledLlmClient(), state=state, plan=plan
        )
        changes = _metric_changes(source.metrics_json, merged_sections, batch.successful_data)
        request_id = str(uuid4())
        trace = {
            "request_id": request_id,
            "mode": "deterministic",
            "analysis_mode": "focused",
            "provider": "none",
            "model": None,
            "selected_tools": selected_tools,
            "planning_used_llm": False,
            "synthesis_used_llm": False,
            "fallback_reasons": synthesis_fallbacks,
            "duration_ms": max(0, round((perf_counter() - started) * 1000)),
            "status": batch.status,
            "tool_executions": [
                item.to_trace().model_dump(mode="json") for item in batch.executions
            ],
            "replan_count": 0,
        }
        targets = source.metrics_json.get("_targets", {})
        metrics = {
            **merged_sections,
            "_targets": targets if isinstance(targets, dict) else {},
            "_agent": trace,
            "_agent_plan": plan.model_dump(mode="json"),
            "_data_resources": data_resource_context(
                {**merged_sections, "_targets": targets}, question=snapshot.question
            ),
            "_correction": {
                "proposal_id": proposal.id,
                "source_analysis_id": source.id,
                "field": proposal.target_field,
                "old_value": proposal.old_value,
                "new_value": proposal.new_value,
                "affected_tools": selected_tools,
                "metric_changes": changes,
            },
        }
        run = AnalysisRun(
            project_id=proposal.project_id,
            stage="operating",
            intent="confirmed_correction",
            status=batch.status,
        )
        self._db.add(run)
        self._db.flush()
        trace["run_id"] = run.id
        result = AnalysisResult(
            project_id=proposal.project_id,
            stage="operating",
            summary=state.summary,
            metrics_json=metrics,
            evidence_json=state.evidence,
            actions_json=state.actions,
            warnings_json=state.warnings,
        )
        self._db.add(result)
        self._db.flush()
        AnalysisInputSnapshotRepository(self._db).create(
            analysis_id=result.id,
            project_id=proposal.project_id,
            input_kind=snapshot.input_kind,
            question=snapshot.question,
            analysis_mode=snapshot.analysis_mode,
            sources=snapshot.sources_json,
            cost_assumptions=assumptions,
        )
        project = self._db.get(Project, proposal.project_id)
        if project is None:
            raise CorrectionConflictError("project is unavailable")
        project.updated_at = utc_now()
        ProjectProfileService(self._db).upsert_confirmed(
            project=project,
            cost_assumptions={proposal.target_field: proposal.new_value},
            source="confirmed_correction",
        )
        AgentTraceRecorder(self._db).record(
            request_id=request_id,
            project_id=proposal.project_id,
            operation="confirmed_correction",
            run_id=run.id,
            analysis_id=result.id,
            initial_plan=plan.model_dump(mode="json"),
            revised_plan=None,
            tool_executions=trace["tool_executions"],
            llm_calls=[],
            selected_memory_ids=[],
            verification_failures=[],
            fallback_reasons=synthesis_fallbacks,
            status=batch.status,
            duration_ms=int(trace["duration_ms"]),
        )
        proposal.status = "applied"
        proposal.applied_analysis_id = result.id
        proposal.updated_at = utc_now()
        self._db.flush()
        return result

    def reject(self, proposal_id: int) -> CorrectionProposal:
        proposal = self._db.get(CorrectionProposal, proposal_id)
        if proposal is None:
            raise LookupError("correction proposal not found")
        if proposal.status != "pending":
            raise CorrectionConflictError("correction proposal is not pending")
        proposal.status = "rejected"
        proposal.updated_at = utc_now()
        self._db.flush()
        return proposal

    def _load_frames(
        self, input_kind: str, sources: dict[str, Any], project_id: int
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if input_kind == "sample":
            sample_dir = Path(__file__).resolve().parents[2] / "sample_data"
            return (
                pd.read_csv(sample_dir / "orders.csv"),
                pd.read_csv(sample_dir / "menu_items.csv"),
                pd.read_csv(sample_dir / "reviews.csv"),
            )
        if input_kind != "uploaded":
            raise CorrectionConflictError("unsupported analysis input kind")
        return tuple(
            self._load_uploaded(sources[name], expected_type, project_id)
            for name, expected_type in (
                ("orders", "orders"),
                ("menu_items", "menu_items"),
                ("reviews", "reviews"),
            )
        )  # type: ignore[return-value]

    def _load_uploaded(
        self, selection: Any, expected_type: str, project_id: int
    ) -> pd.DataFrame:
        if not isinstance(selection, dict):
            raise CorrectionConflictError("uploaded input selection is invalid")
        row = self._db.get(UploadedFile, selection.get("file_id"))
        if row is None or row.project_id != project_id or row.file_type != expected_type:
            raise CorrectionConflictError("uploaded input is unavailable")
        upload_root = Path("storage/uploads").resolve()
        path = Path(row.storage_path).resolve()
        if not path.is_relative_to(upload_root):
            raise CorrectionConflictError("uploaded input path is invalid")
        frame = read_csv_path(path)
        prepared = prepare_frame(
            frame,
            file_type=expected_type,
            mapping=selection.get("mapping", {}),
        )
        return validate_and_clean(prepared, expected_type)


def _metric_changes(
    old_metrics: dict[str, Any],
    merged_sections: dict[str, Any],
    updated_sections: dict[str, Any],
) -> list[dict[str, Any]]:
    changes = []
    for section in updated_sections:
        old = old_metrics.get(section, {})
        new = merged_sections.get(section, {})
        if not isinstance(old, dict) or not isinstance(new, dict):
            continue
        for key, new_value in new.items():
            old_value = old.get(key)
            if isinstance(new_value, (int, float, str)) and old_value != new_value:
                changes.append(
                    {
                        "path": f"metrics.{section}.{key}",
                        "old_value": old_value,
                        "new_value": new_value,
                    }
                )
    return changes[:40]
