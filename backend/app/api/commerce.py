from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUser,
    auth_is_disabled,
    get_current_user,
    require_admin,
    require_owned_project,
)
from app.commerce.contracts import CommerceAnalysisMode
from app.commerce.plan import (
    CommercePlanRequest,
    CommercePlanResponse,
    CommercePlanService,
    CommercePlanStatus,
)
from app.commerce.registry import commerce_dataset_registry
from app.commerce.talk import (
    CommerceTalkRequest,
    CommerceTalkResponse,
    CommerceTalkService,
)
from app.db.models import CommercePlan
from app.db.session import get_db

router = APIRouter(prefix="/commerce", tags=["commerce"])


@router.post("/talk", response_model=CommerceTalkResponse)
def commerce_talk(
    payload: CommerceTalkRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommerceTalkResponse:
    scope = payload.interaction.scope
    require_owned_project(db, current_user, scope.project_id)

    dataset = _resolve_benchmark_dataset(scope.snapshot_id, scope.mode)

    return CommerceTalkService().answer(payload, dataset)


@router.post(
    "/plans",
    response_model=CommercePlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_commerce_plan(
    payload: CommercePlanRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanResponse:
    project = require_owned_project(db, current_user, payload.interaction.scope.project_id)
    require_admin(current_user)
    scope = payload.interaction.scope
    dataset = _resolve_benchmark_dataset(scope.snapshot_id, scope.mode)
    draft = CommercePlanService().draft(payload, dataset)
    if draft.status is CommercePlanStatus.INSUFFICIENT_DATA:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "insufficient_data_for_plan",
                "message": "当前快照没有足够的商品销售证据生成 Plan",
            },
        )

    plan = CommercePlan(
        project_id=project.id,
        created_by_user_id=None if auth_is_disabled() else current_user.id,
        snapshot_id=scope.snapshot_id,
        scope_mode=scope.mode.value,
        question=payload.question,
        status=draft.status.value,
        title=draft.title,
        objective=draft.objective,
        steps_json=[step.model_dump(mode="json") for step in draft.steps],
        evidence_json=list(draft.evidence),
        limitations_json=list(draft.limitations),
    )
    db.add(plan)
    project.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.get("/plans/{plan_id}", response_model=CommercePlanResponse)
def get_commerce_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanResponse:
    plan = db.get(CommercePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="commerce plan not found")
    require_owned_project(db, current_user, plan.project_id)
    return _serialize_plan(plan)


@router.post("/plans/{plan_id}/approve", response_model=CommercePlanResponse)
def approve_commerce_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanResponse:
    plan = db.get(CommercePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="commerce plan not found")
    require_owned_project(db, current_user, plan.project_id)
    require_admin(current_user)
    if plan.status != CommercePlanStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "commerce_plan_not_draft",
                "message": "only draft commerce plans can be approved",
            },
        )
    plan.status = CommercePlanStatus.APPROVED.value
    plan.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


def _resolve_benchmark_dataset(snapshot_id: str | None, mode: CommerceAnalysisMode):
    if snapshot_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "snapshot_required",
                "message": "commerce request requires an explicit snapshot_id",
            },
        )
    if mode is CommerceAnalysisMode.MERCHANT:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "merchant_scope_not_ready",
                "message": (
                    "merchant commerce scope requires the Organization/Store resource "
                    "model and authorization path"
                ),
            },
        )
    dataset = commerce_dataset_registry.get(snapshot_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    if dataset.snapshot.mode is not mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "commerce_scope_snapshot_mismatch",
                "message": "commerce scope mode does not match snapshot mode",
            },
        )
    return dataset


def _serialize_plan(plan: CommercePlan) -> CommercePlanResponse:
    return CommercePlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        snapshot_id=plan.snapshot_id,
        scope_mode=plan.scope_mode,
        question=plan.question,
        status=plan.status,
        title=plan.title,
        objective=plan.objective,
        steps=tuple(plan.steps_json),
        evidence=tuple(plan.evidence_json),
        limitations=tuple(plan.limitations_json),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        approved_at=plan.approved_at,
    )
