from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, AnalysisRun, Project, UploadedFile
from app.db.session import get_db
from app.schemas.operating import (
    OperatingAnalyzeRequest,
    OperatingAnalyzeSampleRequest,
    OperatingFileSelection,
)
from app.services.agent_service import AgentService
from app.services.csv_ingestion_service import (
    CsvIngestionError,
    prepare_frame,
    read_csv_path,
    validate_and_clean,
)

router = APIRouter(prefix="/operating", tags=["operating"])

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@router.post("/analyze")
def analyze_operating(
    payload: OperatingAnalyzeRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    _require_operating_project(db, payload.project_id)
    try:
        orders = _load_selection(db, payload.project_id, "orders", payload.orders)
        menu = _load_selection(db, payload.project_id, "menu_items", payload.menu_items)
        reviews = _load_selection(db, payload.project_id, "reviews", payload.reviews)
    except CsvIngestionError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": str(error)},
        ) from error

    missing_menu_items = sorted(set(orders["item_name"]) - set(menu["item_name"]))
    if missing_menu_items:
        preview = ", ".join(missing_menu_items[:5])
        raise HTTPException(
            status_code=422,
            detail={
                "code": "missing_menu_items",
                "message": f"菜品成本表缺少订单中的菜品：{preview}",
            },
        )

    report = AgentService().analyze_operating(
        project_id=payload.project_id,
        question=payload.question,
        analysis_mode=payload.analysis_mode,
        orders=orders,
        menu=menu,
        reviews=reviews,
        cost_assumptions=payload.cost_assumptions.model_dump(mode="json"),
    )
    return _persist_report(db, report)


@router.post("/analyze-sample")
def analyze_operating_sample(
    payload: OperatingAnalyzeSampleRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    _require_operating_project(db, payload.project_id)
    service = AgentService()
    report = service.analyze_operating(
        project_id=payload.project_id,
        question=payload.question,
        analysis_mode=payload.analysis_mode,
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
        cost_assumptions={
            "monthly_rent": 18000.0,
            "monthly_labor": 24000.0,
            "monthly_utilities": 3000.0,
            "monthly_marketing": 2000.0,
            "other_fixed_costs": 3000.0,
            "cash_balance": 120000.0,
            "delivery_commission_rate": 0.2,
            "delivery_packaging_per_order": 1.5,
        },
    )

    return _persist_report(db, report)


def _persist_report(db: Session, report: dict[str, object]) -> dict[str, object]:
    agent_trace = dict(report.get("agent_trace", {}))  # type: ignore[arg-type]
    run_status = str(agent_trace.get("status", "completed"))
    if run_status not in {"completed", "degraded", "failed"}:
        run_status = "failed"
    run = AnalysisRun(
        project_id=int(report["project_id"]),
        stage="operating",
        intent=str(report["intent"]),
        status=run_status,
    )
    db.add(run)
    db.flush()
    metrics = dict(report["metrics"])  # type: ignore[arg-type]
    agent_trace["run_id"] = run.id
    metrics["_agent"] = agent_trace
    result = AnalysisResult(
        project_id=int(report["project_id"]),
        stage="operating",
        summary=str(report["summary"]),
        metrics_json=metrics,
        evidence_json=report["evidence"],  # type: ignore[arg-type]
        actions_json=report["actions"],  # type: ignore[arg-type]
        warnings_json=report["warnings"],  # type: ignore[arg-type]
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        "analysis_id": result.id,
        **report,
        "run_id": run.id,
        "metrics": metrics,
        "agent_trace": agent_trace,
    }


def _require_operating_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "project_not_found", "message": "project not found"},
        )
    if project.stage != "operating":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_project_stage",
                "message": "operating analysis requires an operating project",
            },
        )
    return project


def _load_selection(
    db: Session,
    project_id: int,
    expected_type: str,
    selection: OperatingFileSelection,
) -> pd.DataFrame:
    row = db.get(UploadedFile, selection.file_id)
    if row is None or row.project_id != project_id:
        raise CsvIngestionError("找不到该项目的上传文件", code="file_not_found")
    if row.file_type != expected_type:
        raise CsvIngestionError(
            f"文件 {row.original_name} 的类型不是 {expected_type}",
            code="file_type_mismatch",
        )
    upload_root = (Path("storage/uploads")).resolve()
    path = Path(row.storage_path).resolve()
    if not path.is_relative_to(upload_root):
        raise CsvIngestionError("上传文件路径无效", code="file_unavailable")
    frame = read_csv_path(path)
    prepared = prepare_frame(
        frame,
        file_type=expected_type,
        mapping=selection.mapping,
    )
    return validate_and_clean(prepared, expected_type)
