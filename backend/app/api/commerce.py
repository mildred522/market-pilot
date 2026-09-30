from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
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
    OlistCategorySalesReport,
    OlistComparisonWindows,
    OlistHotProductReport,
    OlistProductSalesReport,
    OlistProductTrendReport,
    OlistSelectionRecommendationReport,
    TimeWindow,
)
from app.commerce.plan import (
    CommercePlanRequest,
    CommercePlanListResponse,
    CommercePlanPracticeCreate,
    CommercePlanPracticeListResponse,
    CommercePlanPracticeRecordResponse,
    CommercePlanResponse,
    CommercePlanService,
    CommercePlanStatus,
    CommercePlanSummary,
)
from app.commerce.providers import OlistDuckDBFactProvider
from app.commerce.repository import CommerceBenchmarkRepository
from app.commerce.snapshot import CommerceSnapshot
from app.commerce.sources.olist import (
    OlistSalesFactRepository,
    OlistSalesFactUnavailable,
)
from app.commerce.talk import (
    CommerceTalkRequest,
    CommerceTalkResponse,
    CommerceTalkService,
)
from app.db.models import CommercePlan, CommercePlanPracticeRecord
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
    "/benchmarks/{snapshot_id}/comparison-windows",
    response_model=OlistComparisonWindows,
)
def get_olist_comparison_windows(
    snapshot_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistComparisonWindows:
    _require_olist_sales_snapshot(db, snapshot_id)
    try:
        return OlistSalesFactRepository().comparison_windows(snapshot_id)
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "commerce_comparison_windows_not_ready", "message": str(error)},
        ) from error


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
    _require_olist_sales_snapshot(db, snapshot_id)
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
    "/benchmarks/{snapshot_id}/category-sales",
    response_model=OlistCategorySalesReport,
)
def get_olist_category_sales(
    snapshot_id: str,
    start: datetime,
    end: datetime,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
) -> OlistCategorySalesReport:
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_commerce_window", "message": "品类分析窗口的 end 必须晚于 start"},
        )
    _require_olist_sales_snapshot(db, snapshot_id)
    try:
        return OlistSalesFactRepository().category_sales(
            snapshot_id, TimeWindow(start=start, end=end)
        )
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "commerce_sales_fact_not_ready", "message": str(error)},
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
    _require_olist_sales_snapshot(db, snapshot_id, error_code="commerce_hot_products_not_ready")
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

    provider = _fact_provider_for_dataset(dataset)
    return CommerceTalkService().answer(payload, dataset, provider=provider)


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
    try:
        draft = CommercePlanService().draft(
            payload,
            dataset,
            provider=_fact_provider_for_dataset(dataset),
        )
    except OlistSalesFactUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "commerce_plan_facts_not_ready",
                "message": str(error),
            },
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_commerce_plan_window",
                "message": str(error),
            },
        ) from error
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


@router.get("/plans", response_model=CommercePlanListResponse)
def list_commerce_plans(
    project_id: int,
    snapshot_id: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanListResponse:
    require_owned_project(db, current_user, project_id)
    require_admin(current_user)
    plans = db.scalars(
        select(CommercePlan)
        .where(CommercePlan.project_id == project_id, CommercePlan.snapshot_id == snapshot_id)
        .order_by(CommercePlan.created_at.desc(), CommercePlan.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return CommercePlanListResponse(
        items=tuple(
            CommercePlanSummary(
                id=plan.id,
                project_id=plan.project_id,
                snapshot_id=plan.snapshot_id,
                status=plan.status,
                title=plan.title,
                question=plan.question,
                created_at=plan.created_at,
                approved_at=plan.approved_at,
            )
            for plan in plans[:limit]
        ),
        next_offset=offset + limit if len(plans) > limit else None,
    )


@router.get("/plans/{plan_id}", response_model=CommercePlanResponse)
def get_commerce_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanResponse:
    return _serialize_plan(_require_owned_admin_plan(db, current_user, plan_id))


@router.post("/plans/{plan_id}/approve", response_model=CommercePlanResponse)
def approve_commerce_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanResponse:
    plan = _require_owned_admin_plan(db, current_user, plan_id)
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


@router.get("/plans/{plan_id}/practice", response_model=CommercePlanPracticeListResponse)
def list_commerce_plan_practice(
    plan_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanPracticeListResponse:
    plan = _require_owned_admin_plan(db, current_user, plan_id)
    _require_benchmark_practice(plan)
    records = db.scalars(
        select(CommercePlanPracticeRecord)
        .where(CommercePlanPracticeRecord.plan_id == plan_id)
        .order_by(CommercePlanPracticeRecord.created_at.desc(), CommercePlanPracticeRecord.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return CommercePlanPracticeListResponse(
        items=tuple(_serialize_practice(record) for record in records[:limit]),
        next_offset=offset + limit if len(records) > limit else None,
    )


@router.post(
    "/plans/{plan_id}/practice",
    response_model=CommercePlanPracticeRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_commerce_plan_practice(
    plan_id: int,
    payload: CommercePlanPracticeCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CommercePlanPracticeRecordResponse:
    plan = _require_owned_admin_plan(db, current_user, plan_id)
    _require_benchmark_practice(plan)
    if plan.status != CommercePlanStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "commerce_plan_not_approved", "message": "approve the plan before recording a practice"},
        )
    if payload.step_index >= len(plan.steps_json):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_commerce_plan_step", "message": "step_index is outside this plan"},
        )
    if payload.kind == "reflection":
        has_scenario = db.scalar(
            select(CommercePlanPracticeRecord.id)
            .where(
                CommercePlanPracticeRecord.plan_id == plan_id,
                CommercePlanPracticeRecord.step_index == payload.step_index,
                CommercePlanPracticeRecord.kind == "scenario",
            )
            .limit(1)
        )
        if has_scenario is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "practice_scenario_required", "message": "record a scenario before its reflection"},
            )
    record = CommercePlanPracticeRecord(
        plan_id=plan_id,
        step_index=payload.step_index,
        kind=payload.kind,
        note=payload.note,
        recorded_by_user_id=None if auth_is_disabled() else current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize_practice(record)


def _require_owned_admin_plan(db: Session, user: CurrentUser, plan_id: int) -> CommercePlan:
    require_admin(user)
    plan = db.get(CommercePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="commerce plan not found")
    require_owned_project(db, user, plan.project_id)
    return plan


def _require_benchmark_practice(plan: CommercePlan) -> None:
    if plan.scope_mode != CommerceAnalysisMode.BENCHMARK.value:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": "merchant_practice_not_ready", "message": "merchant action tracking is not available"},
        )


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
    analysis_source = CommerceBenchmarkRepository(db).get_for_analysis(snapshot_id)
    if analysis_source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    snapshot = (
        analysis_source
        if isinstance(analysis_source, CommerceSnapshot)
        else analysis_source.snapshot
    )
    if snapshot.mode is not mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "commerce_scope_snapshot_mismatch",
                "message": "commerce scope mode does not match snapshot mode",
            },
        )
    return analysis_source


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


def _require_olist_sales_snapshot(
    db: Session, snapshot_id: str, *, error_code: str = "commerce_sales_fact_not_ready"
) -> CommerceSnapshot:
    snapshot = CommerceBenchmarkRepository(db).get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "commerce_snapshot_not_found",
                "message": "commerce snapshot not found",
            },
        )
    if snapshot.schema_version != "olist-canonical-v2":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": error_code,
                "message": "当前快照还没有 Olist 商品销售事实层",
            },
        )
    return snapshot


def _fact_provider_for_dataset(dataset):
    snapshot = dataset if isinstance(dataset, CommerceSnapshot) else dataset.snapshot
    if snapshot.schema_version == "olist-canonical-v2":
        return OlistDuckDBFactProvider(
            snapshot_id=snapshot.snapshot_id,
            repository=OlistSalesFactRepository(),
        )
    return None


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


def _serialize_practice(record: CommercePlanPracticeRecord) -> CommercePlanPracticeRecordResponse:
    return CommercePlanPracticeRecordResponse(
        id=record.id,
        plan_id=record.plan_id,
        step_index=record.step_index,
        kind=record.kind,
        note=record.note,
        recorded_by_user_id=record.recorded_by_user_id,
        created_at=record.created_at,
    )
