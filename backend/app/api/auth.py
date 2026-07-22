from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.admin_accounts import (
    CSRF_COOKIE,
    PASSWORD_HASHER,
    SESSION_COOKIE,
    authenticate_admin,
    create_admin_session,
    public_admin,
    revoke_admin_session,
    validate_password,
    verify_password,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.security import AuthenticatedActor, get_current_actor
from app.models.admin import AdminSession, AdminUser
from sqlmodel import select
from datetime import UTC, datetime

router = APIRouter(prefix="/api/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def set_auth_cookies(response: Response, raw_session: str, raw_csrf: str, settings: Settings) -> None:
    secure = settings.security_mode == "production"
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        max_age=24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        raw_csrf,
        max_age=24 * 60 * 60,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    user = authenticate_admin(session, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    raw_session, raw_csrf, _ = create_admin_session(
        session,
        user,
        request_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    set_auth_cookies(response, raw_session, raw_csrf, settings)
    return {"authenticated": True, "user": public_admin(user)}


@router.get("/me")
def me(actor: Annotated[AuthenticatedActor, Depends(get_current_actor)]) -> dict[str, object]:
    return {
        "authenticated": True,
        "user": {
            "user_id": actor.actor_id,
            "username": actor.username,
            "display_name": actor.display_name,
            "active": True,
            "must_change_password": actor.must_change_password,
        },
        "authentication_method": actor.auth_method,
    }


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
) -> Response:
    raw_session = request.cookies.get(SESSION_COOKIE)
    if raw_session:
        revoke_admin_session(session, raw_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
) -> dict[str, object]:
    user = session.get(AdminUser, actor.actor_id)
    if user is None or actor.auth_method != "session" or not verify_password(user, payload.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=422, detail="New password must be different")
    timestamp = datetime.now(UTC)
    user.password_hash = PASSWORD_HASHER.hash(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = timestamp
    user.updated_at = timestamp
    current_digest = request.cookies.get(SESSION_COOKIE)
    for admin_session in session.exec(select(AdminSession).where(AdminSession.user_id == user.user_id)).all():
        if current_digest and admin_session.session_digest == hashlib.sha256(current_digest.encode()).hexdigest():
            admin_session.password_verified_at = timestamp
        else:
            admin_session.revoked_at = timestamp
        session.add(admin_session)
    session.add(user)
    session.commit()
    return {"changed": True, "must_change_password": False}
