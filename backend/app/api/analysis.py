from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult
from app.db.session import get_db

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: int, db: Session = Depends(get_db)
) -> dict[str, object]:
    result = db.get(AnalysisResult, analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    return {
        "analysis_id": result.id,
        "project_id": result.project_id,
        "stage": result.stage,
        "summary": result.summary,
        "metrics": result.metrics_json,
        "evidence": result.evidence_json,
        "actions": result.actions_json,
        "risks": result.warnings_json,
        "agent_trace": result.metrics_json.get("_agent"),
        "agent_plan": result.metrics_json.get("_agent_plan"),
    }
