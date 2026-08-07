from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.models import Project
from app.db.session import get_db
from app.schemas.common import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(name=payload.name, stage=payload.stage)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project
