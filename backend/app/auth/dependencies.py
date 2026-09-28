from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_session_token
from app.db.models import AnalysisResult, AuthSession, Project, User
from app.db.session import get_db

SESSION_COOKIE_NAME = "market_pilot_session"
CSRF_COOKIE_NAME = "market_pilot_csrf"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    is_admin: bool


def auth_is_disabled() -> bool:
    # The bypass exists solely for isolated tests. A production or local runtime
    # must not lose ownership checks because an environment variable was copied.
    return (
        os.getenv("APP_ENV", "").strip().lower() == "test"
        and os.getenv("AUTH_DISABLED", "false").strip().lower()
        in {"1", "true", "yes"}
    )


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> CurrentUser:
    if auth_is_disabled():
        return CurrentUser(id=TEST_USER_ID, email="test@market-pilot.local", is_admin=True)

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise _unauthenticated()
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
    )
    if session is None or session.revoked_at is not None or _is_expired(session.expires_at):
        raise _unauthenticated()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_token = request.headers.get("X-CSRF-Token", "")
        if not csrf_token or not session.csrf_token_hash or hash_session_token(csrf_token) != session.csrf_token_hash:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf validation failed")
    user = db.get(User, session.user_id)
    if user is None:
        raise _unauthenticated()
    return CurrentUser(id=user.id, email=user.email, is_admin=user.is_admin)


def require_owned_project(db: Session, user: CurrentUser, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None or (not auth_is_disabled() and project.owner_user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


def require_owned_analysis(
    db: Session, user: CurrentUser, analysis_id: int
) -> AnalysisResult:
    analysis = db.get(AnalysisResult, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis not found")
    require_owned_project(db, user, analysis.project_id)
    return analysis


def require_admin(user: CurrentUser) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return user


def _is_expired(value: datetime) -> bool:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized <= datetime.now(UTC)


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Session"},
    )
