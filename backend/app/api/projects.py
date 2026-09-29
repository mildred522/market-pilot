from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUser,
    auth_is_disabled,
    get_current_user,
    require_owned_project,
)
from app.db.models import AnalysisConversation, AnalysisResult, Project
from app.db.session import get_db
from app.schemas.common import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(
    query: str = Query(default="", max_length=120),
    stage: str | None = Query(default=None, pattern="^(pre_open|operating)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    statement = select(Project)
    if not auth_is_disabled():
        statement = statement.where(Project.owner_user_id == current_user.id)
    if query.strip():
        statement = statement.where(Project.name.contains(query.strip()))
    if stage is not None:
        statement = statement.where(Project.stage == stage)
    projects = list(
        db.scalars(
            statement.order_by(Project.updated_at.desc(), Project.id.desc())
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )
    has_more = len(projects) > limit
    return {
        "items": [_project_item(project) for project in projects[:limit]],
        "next_offset": offset + limit if has_more else None,
    }


@router.get("/{project_id}/analyses")
def list_project_analyses(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    project = require_owned_project(db, current_user, project_id)
    rows = db.execute(
        select(AnalysisResult, AnalysisConversation)
        .outerjoin(
            AnalysisConversation,
            AnalysisConversation.analysis_id == AnalysisResult.id,
        )
        .where(AnalysisResult.project_id == project.id)
        .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc())
        .limit(limit)
    ).all()
    return {
        "project": _project_item(project),
        "items": [
            {
                "id": analysis.id,
                "stage": analysis.stage,
                "summary": analysis.summary,
                "created_at": analysis.created_at,
                "conversation_id": conversation.id if conversation is not None else None,
                "conversation_updated_at": (
                    conversation.updated_at if conversation is not None else None
                ),
            }
            for analysis, conversation in rows
        ],
    }


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Project:
    project = Project(
        name=payload.name,
        stage=payload.stage,
        owner_user_id=None if auth_is_disabled() else current_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _project_item(project: Project) -> dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "stage": project.stage,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
