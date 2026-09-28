from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, get_current_user, require_owned_analysis, require_owned_project
from app.corrections.repository import CorrectionProposalRepository
from app.corrections.service import (
    CorrectionConflictError,
    CorrectionExecutionError,
    CorrectionWorkflowService,
)
from app.db.models import AnalysisResult, CorrectionProposal
from app.db.session import get_db
from app.schemas.corrections import CorrectionConfirmRequest

router = APIRouter(tags=["corrections"])


@router.get("/analysis/{analysis_id}/corrections")
def list_corrections(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, object]]:
    require_owned_analysis(db, current_user, analysis_id)
    return [
        _serialize(item)
        for item in CorrectionProposalRepository(db).list_for_analysis(analysis_id)
    ]


@router.post("/corrections/{proposal_id}/confirm")
def confirm_correction(
    proposal_id: int,
    payload: CorrectionConfirmRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    proposal = db.get(CorrectionProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="correction proposal not found")
    require_owned_project(db, current_user, proposal.project_id)
    service = CorrectionWorkflowService(db)
    try:
        result = service.apply(
            proposal_id, idempotency_key=payload.idempotency_key
        )
        db.commit()
    except LookupError as error:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CorrectionConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CorrectionExecutionError as error:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "correction_recompute_failed", "message": str(error)},
        ) from error
    proposal = db.get(CorrectionProposal, proposal_id)
    return {
        "proposal": _serialize(proposal),
        "analysis_id": result.id,
        "source_analysis_id": proposal.source_analysis_id,
        "summary": result.summary,
        "metric_changes": result.metrics_json.get("_correction", {}).get(
            "metric_changes", []
        ),
    }


@router.post("/corrections/{proposal_id}/reject")
def reject_correction(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    proposal = db.get(CorrectionProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="correction proposal not found")
    require_owned_project(db, current_user, proposal.project_id)
    try:
        proposal = CorrectionWorkflowService(db).reject(proposal_id)
        db.commit()
    except LookupError as error:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CorrectionConflictError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _serialize(proposal)


def _serialize(proposal: CorrectionProposal | None) -> dict[str, object]:
    if proposal is None:
        raise LookupError("correction proposal not found")
    return {
        "id": proposal.id,
        "source_analysis_id": proposal.source_analysis_id,
        "source_answer_version_id": proposal.source_answer_version_id,
        "field": proposal.target_field,
        "old_value": proposal.old_value,
        "new_value": proposal.new_value,
        "reason": proposal.reason,
        "status": proposal.status,
        "idempotency_key": proposal.idempotency_key,
        "applied_analysis_id": proposal.applied_analysis_id,
        "error_code": proposal.error_code,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }
