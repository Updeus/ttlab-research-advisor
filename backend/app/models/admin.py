from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class AdminUser(SQLModel, table=True):
    user_id: str = Field(primary_key=True)
    username: str = Field(unique=True, index=True, max_length=80)
    display_name: str = Field(max_length=120)
    password_hash: str
    active: bool = Field(default=True, index=True)
    must_change_password: bool = True
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = Field(default=None, index=True)
    password_changed_at: datetime = Field(default_factory=utc_now)
    last_login_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
    created_by: Optional[str] = Field(default=None, index=True)


class AdminSession(SQLModel, table=True):
    session_digest: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="adminuser.user_id", index=True)
    csrf_digest: str = Field(max_length=64)
    issued_at: datetime = Field(default_factory=utc_now, index=True)
    last_seen_at: datetime = Field(default_factory=utc_now, index=True)
    idle_expires_at: datetime = Field(index=True)
    absolute_expires_at: datetime = Field(index=True)
    password_verified_at: datetime = Field(default_factory=utc_now)
    revoked_at: Optional[datetime] = Field(default=None, index=True)
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None


class FeatureSetting(SQLModel, table=True):
    feature_key: str = Field(primary_key=True, max_length=80)
    enabled: bool = Field(default=True, index=True)
    disabled_message: Optional[str] = None
    updated_by: Optional[str] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class OllamaModelPolicy(SQLModel, table=True):
    model_name: str = Field(primary_key=True, max_length=255)
    digest: str = Field(max_length=64)
    enabled: bool = Field(default=True, index=True)
    is_default: bool = Field(default=False, index=True)
    last_seen_at: datetime = Field(default_factory=utc_now, index=True)
    updated_by: Optional[str] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class BulkOperation(SQLModel, table=True):
    operation_id: str = Field(primary_key=True)
    operation_type: str = Field(index=True)
    status: str = Field(default="previewed", index=True)
    preview_hash: str = Field(max_length=64, index=True)
    request_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    preview_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    result_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    requested_by: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    expires_at: datetime = Field(index=True)
    executed_at: Optional[datetime] = Field(default=None, index=True)
