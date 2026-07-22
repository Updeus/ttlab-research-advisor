from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlmodel import Session, select

from app.models.admin import AdminSession, AdminUser

SESSION_COOKIE = "ttlab_admin_session"
CSRF_COOKIE = "ttlab_admin_csrf"
SESSION_IDLE_HOURS = 8
SESSION_ABSOLUTE_HOURS = 24
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_MINUTES = 15
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,79}$")
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username must be 3-80 lowercase letters, numbers, dots, dashes, or underscores")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if len(password) > 256:
        raise ValueError("Password is too long")


def create_admin_user(
    session: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    created_by: str | None,
    must_change_password: bool,
) -> AdminUser:
    normalized = normalize_username(username)
    validate_password(password)
    if session.exec(select(AdminUser).where(AdminUser.username == normalized)).first():
        raise ValueError("An admin with this username already exists")
    now = utc_now()
    user = AdminUser(
        user_id=str(uuid4()),
        username=normalized,
        display_name=display_name.strip() or normalized,
        password_hash=PASSWORD_HASHER.hash(password),
        must_change_password=must_change_password,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
        created_by=created_by,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_admin(session: Session, username: str, password: str) -> AdminUser | None:
    normalized = username.strip().lower()
    user = session.exec(select(AdminUser).where(AdminUser.username == normalized)).first()
    if user is None or not user.active:
        # Make an unknown account meaningfully expensive without revealing it.
        PASSWORD_HASHER.hash(password[:256] or "invalid-password")
        return None
    now = utc_now()
    if aware(user.locked_until) and aware(user.locked_until) > now:
        return None
    try:
        valid = PASSWORD_HASHER.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= LOGIN_FAILURE_LIMIT:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            user.failed_login_attempts = 0
        user.updated_at = now
        session.add(user)
        session.commit()
        return None
    if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = PASSWORD_HASHER.hash(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.updated_at = now
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def verify_password(user: AdminUser, password: str) -> bool:
    try:
        return bool(PASSWORD_HASHER.verify(user.password_hash, password))
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_admin_session(
    session: Session,
    user: AdminUser,
    *,
    request_ip: str | None,
    user_agent: str | None,
) -> tuple[str, str, AdminSession]:
    raw_session = secrets.token_urlsafe(48)
    raw_csrf = secrets.token_urlsafe(32)
    now = utc_now()
    record = AdminSession(
        session_digest=digest_secret(raw_session),
        csrf_digest=digest_secret(raw_csrf),
        user_id=user.user_id,
        issued_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=SESSION_IDLE_HOURS),
        absolute_expires_at=now + timedelta(hours=SESSION_ABSOLUTE_HOURS),
        password_verified_at=now,
        request_ip=request_ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    session.add(record)
    session.commit()
    return raw_session, raw_csrf, record


def resolve_admin_session(session: Session, raw_session: str) -> tuple[AdminSession, AdminUser] | None:
    record = session.get(AdminSession, digest_secret(raw_session))
    now = utc_now()
    if (
        record is None
        or record.revoked_at is not None
        or aware(record.idle_expires_at) <= now
        or aware(record.absolute_expires_at) <= now
    ):
        return None
    user = session.get(AdminUser, record.user_id)
    if user is None or not user.active:
        return None
    record.last_seen_at = now
    record.idle_expires_at = min(now + timedelta(hours=SESSION_IDLE_HOURS), aware(record.absolute_expires_at))
    session.add(record)
    session.commit()
    return record, user


def revoke_admin_session(session: Session, raw_session: str) -> None:
    record = session.get(AdminSession, digest_secret(raw_session))
    if record and record.revoked_at is None:
        record.revoked_at = utc_now()
        session.add(record)
        session.commit()


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_admin(user: AdminUser) -> dict[str, object]:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "active": user.active,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }
