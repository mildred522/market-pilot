from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import AnalysisResult, PreOpenInput, Project
from app.db.session import get_db
from app.schemas.pre_open import PreOpenAnalyzeRequest, PreOpenAnalyzeResponse
from app.memory.project_profile import ProjectProfileService

router = APIRouter(prefix="/pre-open", tags=["pre-open"])


@router.post("/analyze", response_model=PreOpenAnalyzeResponse)
def analyze_pre_open(
    payload: PreOpenAnalyzeRequest, db: Session = Depends(get_db)
) -> PreOpenAnalyzeResponse:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    pre_open_input = PreOpenInput(**payload.model_dump())
    db.add(pre_open_input)

    estimated_daily_revenue = (
        payload.expected_daily_orders * payload.expected_avg_order_value
    )
    estimated_daily_gross_profit = round(
        estimated_daily_revenue * payload.expected_gross_margin, 2
    )
    daily_rent = round(payload.monthly_rent / 30, 2)

    risks: list[str] = []
    if payload.debt_amount > payload.own_capital * 0.6:
        risks.append("负债占比较高，现金流抗压能力偏弱")
    if payload.competitor_count >= 6:
        risks.append("周边竞品密度较高，需要明确差异化")
    if payload.is_franchise and payload.franchise_fee > 50000:
        risks.append("加盟投入较高，需要核验真实门店流水")

    if estimated_daily_gross_profit <= daily_rent:
        risks.append("预估日毛利不足以覆盖日均房租")

    actions = [
        "开店前连续 3 天蹲点记录午市和晚市客流",
        "向至少 2 家同品类竞品估算订单量和价格带",
        "核验加盟品牌直营店流水和老加盟商闭店情况",
    ]

    summary = "当前项目需要重点核验租金、竞品密度和加盟投入是否匹配预估流水。"

    result = AnalysisResult(
        project_id=payload.project_id,
        stage="pre_open",
        summary=summary,
        metrics_json={
            "estimated_daily_revenue": estimated_daily_revenue,
            "estimated_daily_gross_profit": estimated_daily_gross_profit,
            "daily_rent": daily_rent,
        },
        evidence_json=[
            f"预计日营收 {estimated_daily_revenue} 元",
            f"预计日毛利 {estimated_daily_gross_profit} 元",
            f"日均房租 {daily_rent} 元",
        ],
        actions_json=actions,
        warnings_json=risks,
    )
    db.add(result)
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
        summary=summary,
        metrics=result.metrics_json,
        risks=risks,
        actions=actions,
    )
