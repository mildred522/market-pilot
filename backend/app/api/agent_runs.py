from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability.contracts import AgentRunDetail, AgentRunSummary
from app.observability.trace_query_service import (
    AgentRunNotFoundError,
    AgentRunQueryService,
)


router = APIRouter(prefix="/analysis", tags=["agent-runs"])


@router.get("/{analysis_id}/agent-runs", response_model=list[AgentRunSummary])
def list_agent_runs(
    analysis_id: int, db: Session = Depends(get_db)
) -> list[AgentRunSummary]:
    try:
        return AgentRunQueryService(db).list_for_analysis(analysis_id)
    except AgentRunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/{analysis_id}/agent-runs/{request_id}", response_model=AgentRunDetail
)
def get_agent_run(
    analysis_id: int,
    request_id: str,
    db: Session = Depends(get_db),
) -> AgentRunDetail:
    try:
        return AgentRunQueryService(db).get_for_analysis(analysis_id, request_id)
    except AgentRunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
