from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult
from app.db.session import get_db
from app.schemas.operating import OperatingAnalyzeSampleRequest
from app.services.agent_service import AgentService

router = APIRouter(prefix="/operating", tags=["operating"])

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@router.post("/analyze")
def analyze_operating() -> dict[str, str]:
    return {"status": "operating API will accept mapped CSV files in Round 5"}


@router.post("/analyze-sample")
def analyze_operating_sample(
    payload: OperatingAnalyzeSampleRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    service = AgentService()
    report = service.analyze_operating(
        project_id=payload.project_id,
        question=payload.question,
        orders=pd.read_csv(SAMPLE_DIR / "orders.csv"),
        menu=pd.read_csv(SAMPLE_DIR / "menu_items.csv"),
        reviews=pd.read_csv(SAMPLE_DIR / "reviews.csv"),
    )

    result = AnalysisResult(
        project_id=payload.project_id,
        stage="operating",
        summary=str(report["summary"]),
        metrics_json=report["metrics"],  # type: ignore[arg-type]
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
    }
