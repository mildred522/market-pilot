from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.corrections.repository import (
    AnalysisInputSnapshotRepository,
    CorrectionProposalRepository,
)
from app.db.models import AnalysisResult, AnswerVersion, Base, Project


def test_snapshot_and_correction_proposal_are_immutable_inputs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="更正测试店", stage="operating")
        db.add(project)
        db.flush()
        analysis = AnalysisResult(
            project_id=project.id,
            stage="operating",
            summary="旧报告",
            metrics_json={},
            evidence_json=[],
            actions_json=[],
            warnings_json=[],
        )
        db.add(analysis)
        db.flush()
        version = AnswerVersion(
            analysis_id=analysis.id,
            conversation_id=1,
            parent_version_id=None,
            original_question="为什么亏损",
            user_feedback="租金改为 25000",
            revision_type="recompute_metrics",
            plan_json={},
            execution_summary_json={},
            answer="待确认",
            sections_json={},
            evidence_refs_json=[],
            quality="confirmation_required",
            validation_json={},
        )
        db.add(version)
        db.flush()

        snapshots = AnalysisInputSnapshotRepository(db)
        snapshot = snapshots.create(
            analysis_id=analysis.id,
            project_id=project.id,
            input_kind="sample",
            question="完整分析",
            analysis_mode="full",
            sources={"sample": True},
            cost_assumptions={"monthly_rent": 18000.0},
        )
        proposal = CorrectionProposalRepository(db).create(
            project_id=project.id,
            source_analysis_id=analysis.id,
            source_answer_version_id=version.id,
            target_field="monthly_rent",
            old_value=snapshot.cost_assumptions_json["monthly_rent"],
            new_value=25000,
            reason="租金应为 25000",
        )

        assert snapshots.get_for_analysis(analysis.id).id == snapshot.id
        assert proposal.status == "pending"
        assert proposal.idempotency_key
        assert proposal.old_value == 18000
