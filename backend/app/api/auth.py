from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import CSRF_COOKIE_NAME, CurrentUser, SESSION_COOKIE_NAME, get_current_user
from app.auth.security import hash_password, hash_session_token, new_session_token, verify_password
from app.db.models import AuthSession, Project, User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_LIFETIME = timedelta(days=14)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)


class UserRead(BaseModel):
    id: str
    email: str
    is_admin: bool


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: Credentials, response: Response, db: Session = Depends(get_db)
) -> UserRead:
    email = _normalize_email(payload.email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    is_first_user = not bool(db.scalar(select(func.count()).select_from(User)))
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.flush()
    if is_first_user:
        # A pre-auth local database has no owner records. Claim it only once,
        # during initial setup, so later accounts cannot access legacy data.
        db.execute(
            update(Project)
            .where(Project.owner_user_id.is_(None))
            .values(owner_user_id=user.id)
        )
    _set_session_cookies(response, *_create_session(db, user))
    db.commit()
    return _serialize_user(user)


@router.post("/login", response_model=UserRead)
def login(
    payload: Credentials, response: Response, db: Session = Depends(get_db)
) -> UserRead:
    email = _normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    _set_session_cookies(response, *_create_session(db, user))
    db.commit()
    return _serialize_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
        )
        if session is not None:
            session.revoked_at = datetime.now(UTC)
            db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser = Depends(get_current_user)) -> UserRead:
    return UserRead(id=user.id, email=user.email, is_admin=user.is_admin)


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid email")
    return email


def _create_session(db: Session, user: User) -> tuple[str, str]:
    token, csrf_token = new_session_token(), new_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            csrf_token_hash=hash_session_token(csrf_token),
            expires_at=datetime.now(UTC) + SESSION_LIFETIME,
        )
    )
    return token, csrf_token


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    secure = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}
    same_site = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        samesite=same_site,
        secure=secure,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        samesite=same_site,
        secure=secure,
    )


def _serialize_user(user: User) -> UserRead:
    return UserRead(id=user.id, email=user.email, is_admin=user.is_admin)
