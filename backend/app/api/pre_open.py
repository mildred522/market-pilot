from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, get_current_user, require_owned_project
from app.db.models import AnalysisResult, PreOpenInput, Project, utc_now
from app.db.session import get_db
from app.schemas.pre_open import PreOpenAnalyzeRequest, PreOpenAnalyzeResponse
from app.memory.project_profile import ProjectProfileService
from app.pre_open.contracts import PreOpenAssessmentInput
from app.pre_open.service import PreOpenAssessmentService

router = APIRouter(prefix="/pre-open", tags=["pre-open"])


@router.post("/analyze", response_model=PreOpenAnalyzeResponse)
def analyze_pre_open(
    payload: PreOpenAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> PreOpenAnalyzeResponse:
    project = require_owned_project(db, current_user, payload.project_id)
    pre_open_input = PreOpenInput(**payload.model_dump())
    db.add(pre_open_input)

    assessment = PreOpenAssessmentService().analyze(
        PreOpenAssessmentInput.model_validate(
            payload.model_dump(
                include={
                    "monthly_rent",
                    "total_investment",
                    "own_capital",
                    "debt_amount",
                    "expected_daily_orders",
                    "expected_avg_order_value",
                    "expected_gross_margin",
                    "is_franchise",
                    "franchise_fee",
                    "competitor_count",
                }
            )
        )
    )
    metrics = assessment.metrics.model_dump()

    result = AnalysisResult(
        project_id=payload.project_id,
        stage="pre_open",
        summary=assessment.summary,
        metrics_json=metrics,
        evidence_json=list(assessment.evidence),
        actions_json=list(assessment.actions),
        warnings_json=list(assessment.risks),
    )
    db.add(result)
    project.updated_at = utc_now()
    ProjectProfileService(db).upsert_confirmed(
        project=project,
        city=payload.city,
        category=payload.category,
        cost_assumptions={
            "monthly_rent": payload.monthly_rent,
            "total_investment": payload.total_investment,
            "own_capital": payload.own_capital,
            "debt_amount": payload.debt_amount,
            "expected_daily_orders": payload.expected_daily_orders,
            "expected_avg_order_value": payload.expected_avg_order_value,
            "expected_gross_margin": payload.expected_gross_margin,
        },
        source="user_input",
    )
    db.commit()
    db.refresh(result)

    return PreOpenAnalyzeResponse(
        analysis_id=result.id,
        project_id=payload.project_id,
        stage="pre_open",
        summary=assessment.summary,
        metrics=result.metrics_json,
        risks=list(assessment.risks),
        actions=list(assessment.actions),
        limitations=list(assessment.limitations),
    )
