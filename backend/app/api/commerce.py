from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUser,
    auth_is_disabled,
    get_current_user,
    require_admin,
    require_owned_project,
)
from app.commerce.contracts import (
    CommerceAnalysisMode,
    CommerceBenchmarkSnapshotSummary,
)
from app.commerce.metrics import (
    ItemLevel,
    OlistHotProductReport,
    OlistProductSalesReport,
    OlistProductTrendReport,
    OlistSelectionRecommendationReport,
    TimeWindow,
)
from app.commerce.plan import (
    CommercePlanRequest,
    CommercePlanResponse,
    CommercePlanService,
    CommercePlanStatus,
)
from app.commerce.repository import CommerceBenchmarkRepository
from app.commerce.sources.olist import (
    OlistSalesFactRepository,
    OlistSalesFactUnavailable,
)
from app.commerce.talk import (
    CommerceTalkRequest,
    CommerceTalkResponse,
    CommerceTalkService,
)
from app.db.models import CommercePlan
from app.db.session import get_db

router = APIRouter(prefix="/commerce", tags=["commerce"])


@router.get(
    "/benchmarks",
    response_model=tuple[CommerceBenchmarkSnapshotSummary, ...],
)
def list_commerce_benchmarks(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> tuple[CommerceBenchmarkSnapshotSummary, ...]:
    return CommerceBenchmarkRepository(db).list()


@router.get(
    "/benchmarks/{snapshot_id}/sales",
    response_model=OlistProductSalesReport,
)
def get_olist_product_sales(
    snapshot_id: str,
    start: datetime,
    end: datetime,
    item_level: ItemLevel = ItemLevel.PRODUCT,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistProductSalesReport:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_window",
                "message": "销售分析窗口的 end 必须晚于 start",
            },
        )
    dataset = CommerceBenchmarkRepository(db).get(snapshot_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    if dataset.snapshot.schema_version != "olist-canonical-v2":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_sales_fact_not_ready",
                "message": "当前快照还没有 Olist 销售事实层",
            },
        )
    try:
        return OlistSalesFactRepository().product_sales(
            snapshot_id,
            TimeWindow(start=start, end=end),
            item_level=item_level,
        )
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_sales_fact_not_ready",
                "message": str(error),
            },
        ) from error


@router.get(
    "/benchmarks/{snapshot_id}/hot-products",
    response_model=OlistHotProductReport,
)
def get_olist_hot_products(
    snapshot_id: str,
    start: datetime,
    end: datetime,
    baseline_start: datetime | None = None,
    baseline_end: datetime | None = None,
    item_level: ItemLevel = ItemLevel.PRODUCT,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistHotProductReport:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_window",
                "message": "热点分析窗口的 end 必须晚于 start",
            },
        )
    if (baseline_start is None) != (baseline_end is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "incomplete_commerce_baseline_window",
                "message": "baseline_start 和 baseline_end 必须同时提供",
            },
        )
    if baseline_start is not None and baseline_end is not None and baseline_end <= baseline_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_baseline_window",
                "message": "基线窗口的 baseline_end 必须晚于 baseline_start",
            },
        )
    duration = end - start
    baseline_window = TimeWindow(
        start=baseline_start or start - duration,
        end=baseline_end or start,
    )
    dataset = CommerceBenchmarkRepository(db).get(snapshot_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    if dataset.snapshot.schema_version != "olist-canonical-v2":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_hot_products_not_ready",
                "message": "当前快照还没有 Olist 商品销售事实层",
            },
        )
    try:
        return OlistSalesFactRepository().hot_products(
            snapshot_id,
            TimeWindow(start=start, end=end),
            baseline_window,
            item_level=item_level,
            limit=limit,
        )
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_hot_products_not_ready",
                "message": str(error),
            },
        ) from error


@router.get(
    "/benchmarks/{snapshot_id}/trends",
    response_model=OlistProductTrendReport,
)
def get_olist_product_trends(
    snapshot_id: str,
    start: datetime,
    end: datetime,
    baseline_start: datetime | None = None,
    baseline_end: datetime | None = None,
    item_level: ItemLevel = ItemLevel.PRODUCT,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistProductTrendReport:
    current_window, baseline_window = _resolve_comparison_windows(
        start,
        end,
        baseline_start,
        baseline_end,
    )
    _require_olist_sales_snapshot(db, snapshot_id)
    try:
        return OlistSalesFactRepository().product_trends(
            snapshot_id,
            current_window,
            baseline_window,
            item_level=item_level,
        )
    except (OlistSalesFactUnavailable, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
            if isinstance(error, ValueError) and not isinstance(error, OlistSalesFactUnavailable)
            else status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "invalid_commerce_trend_window"
                if isinstance(error, ValueError) and not isinstance(error, OlistSalesFactUnavailable)
                else "commerce_trends_not_ready",
                "message": str(error),
            },
        ) from error


@router.get(
    "/benchmarks/{snapshot_id}/selection-recommendations",
    response_model=OlistSelectionRecommendationReport,
)
def get_olist_selection_recommendations(
    snapshot_id: str,
    start: datetime,
    end: datetime,
    baseline_start: datetime | None = None,
    baseline_end: datetime | None = None,
    item_level: ItemLevel = ItemLevel.PRODUCT,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistSelectionRecommendationReport:
    current_window, baseline_window = _resolve_comparison_windows(
        start,
        end,
        baseline_start,
        baseline_end,
    )
    _require_olist_sales_snapshot(db, snapshot_id)
    try:
        return OlistSalesFactRepository().selection_recommendations(
            snapshot_id,
            current_window,
            baseline_window,
            item_level=item_level,
            limit=limit,
        )
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_selection_recommendations_not_ready",
                "message": str(error),
            },
        ) from error


@router.post("/talk", response_model=CommerceTalkResponse)
def commerce_talk(
    payload: CommerceTalkRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommerceTalkResponse:
    scope = payload.interaction.scope
    require_owned_project(db, current_user, scope.project_id)

    dataset = _resolve_benchmark_dataset(db, scope.snapshot_id, scope.mode)

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
    dataset = _resolve_benchmark_dataset(db, scope.snapshot_id, scope.mode)
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


def _resolve_benchmark_dataset(
    db: Session, snapshot_id: str | None, mode: CommerceAnalysisMode
):
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
    dataset = CommerceBenchmarkRepository(db).get(snapshot_id)
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


def _resolve_comparison_windows(
    start: datetime,
    end: datetime,
    baseline_start: datetime | None,
    baseline_end: datetime | None,
) -> tuple[TimeWindow, TimeWindow]:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_window",
                "message": "趋势分析窗口的 end 必须晚于 start",
            },
        )
    if (baseline_start is None) != (baseline_end is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "incomplete_commerce_baseline_window",
                "message": "baseline_start 和 baseline_end 必须同时提供",
            },
        )
    duration = end - start
    resolved_baseline_start = baseline_start or start - duration
    resolved_baseline_end = baseline_end or start
    if resolved_baseline_end <= resolved_baseline_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_baseline_window",
                "message": "基线窗口的 baseline_end 必须晚于 baseline_start",
            },
        )
    current_window = TimeWindow(start=start, end=end)
    baseline_window = TimeWindow(
        start=resolved_baseline_start,
        end=resolved_baseline_end,
    )
    if current_window.end - current_window.start != baseline_window.end - baseline_window.start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unequal_commerce_windows",
                "message": "当前窗口和基线窗口必须等长",
            },
        )
    return current_window, baseline_window


def _require_olist_sales_snapshot(db: Session, snapshot_id: str):
    dataset = CommerceBenchmarkRepository(db).get(snapshot_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    if dataset.snapshot.schema_version != "olist-canonical-v2":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_sales_fact_not_ready",
                "message": "当前快照还没有 Olist 商品销售事实层",
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
