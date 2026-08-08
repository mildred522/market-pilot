from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisResult,
    LocationAnalysis,
    Project,
    UploadedFile,
)
from app.db.session import get_db
from app.schemas.dashboard import (
    AgentIntegrationUpdate,
    BaiduIntegrationUpdate,
    IntegrationName,
)
from app.services.runtime_config import runtime_config

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict[str, object]:
    stage_counts = dict(
        db.execute(
            select(Project.stage, func.count(Project.id)).group_by(Project.stage)
        ).all()
    )
    recent_rows = db.execute(
        select(AnalysisResult, Project.name)
        .join(Project, Project.id == AnalysisResult.project_id)
        .order_by(AnalysisResult.id.desc())
        .limit(5)
    ).all()
    return {
        "workspace": {
            "name": "Market Pilot 本地工作区",
            "role": "Owner",
            "account_mode": "local",
        },
        "counts": {
            "projects": _count(db, Project),
            "pre_open_projects": int(stage_counts.get("pre_open", 0)),
            "operating_projects": int(stage_counts.get("operating", 0)),
            "analyses": _count(db, AnalysisResult),
            "uploaded_files": _count(db, UploadedFile),
            "location_analyses": _count(db, LocationAnalysis),
        },
        "integrations": runtime_config.status(),
        "recent_analyses": [
            {
                "id": analysis.id,
                "project_id": analysis.project_id,
                "project_name": project_name,
                "stage": analysis.stage,
                "summary": analysis.summary,
            }
            for analysis, project_name in recent_rows
        ],
    }


@router.put("/integrations/baidu")
def update_baidu(payload: BaiduIntegrationUpdate) -> dict[str, object]:
    runtime_config.set_baidu_key(payload.api_key)
    return runtime_config.status()["baidu"]


@router.put("/integrations/agent")
def update_agent(payload: AgentIntegrationUpdate) -> dict[str, object]:
    runtime_config.set_agent(
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
        provider=payload.provider,
    )
    return runtime_config.status()["agent"]


@router.delete("/integrations/{integration}")
def clear_integration(integration: IntegrationName) -> dict[str, object]:
    runtime_config.clear(integration)
    return runtime_config.status()[integration]


def _count(db: Session, model: type[object]) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)
