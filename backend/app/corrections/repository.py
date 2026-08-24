from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisInputSnapshot, CorrectionProposal


class AnalysisInputSnapshotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        analysis_id: int,
        project_id: int,
        input_kind: str,
        question: str,
        analysis_mode: str,
        sources: dict[str, Any],
        cost_assumptions: dict[str, Any],
    ) -> AnalysisInputSnapshot:
        snapshot = AnalysisInputSnapshot(
            analysis_id=analysis_id,
            project_id=project_id,
            input_kind=input_kind,
            question=question[:4000],
            analysis_mode=analysis_mode,
            sources_json=sources,
            cost_assumptions_json=cost_assumptions,
        )
        self._db.add(snapshot)
        self._db.flush()
        return snapshot

    def get_for_analysis(self, analysis_id: int) -> AnalysisInputSnapshot | None:
        return self._db.scalar(
            select(AnalysisInputSnapshot).where(
                AnalysisInputSnapshot.analysis_id == analysis_id
            )
        )


class CorrectionProposalRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        project_id: int,
        source_analysis_id: int,
        source_answer_version_id: int,
        target_field: str,
        old_value: float,
        new_value: float,
        reason: str,
    ) -> CorrectionProposal:
        proposal = CorrectionProposal(
            project_id=project_id,
            source_analysis_id=source_analysis_id,
            source_answer_version_id=source_answer_version_id,
            target_field=target_field,
            old_value=old_value,
            new_value=new_value,
            reason=reason[:1000],
            status="pending",
            idempotency_key=str(uuid4()),
        )
        self._db.add(proposal)
        self._db.flush()
        return proposal

    def get(self, proposal_id: int) -> CorrectionProposal | None:
        return self._db.get(CorrectionProposal, proposal_id)

    def list_for_analysis(self, analysis_id: int) -> list[CorrectionProposal]:
        return list(
            self._db.scalars(
                select(CorrectionProposal)
                .where(CorrectionProposal.source_analysis_id == analysis_id)
                .order_by(CorrectionProposal.id)
            ).all()
        )
