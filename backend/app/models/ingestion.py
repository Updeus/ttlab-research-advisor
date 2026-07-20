from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionRun(SQLModel, table=True):
    run_id: str = Field(primary_key=True)
    source: str = Field(default="ttlab", index=True)
    trigger: str = Field(index=True)
    requested_by: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="running", index=True)
    discovered_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    downloaded_count: int = 0
    extracted_count: int = 0
    chunked_count: int = 0
    error_message: Optional[str] = None
    summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    started_at: datetime = Field(default_factory=utc_now, index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)


class IngestionSyncState(SQLModel, table=True):
    source: str = Field(default="ttlab", primary_key=True)
    lock_owner: Optional[str] = Field(default=None, index=True)
    locked_until: Optional[datetime] = Field(default=None, index=True)
    manual_requested_at: Optional[datetime] = Field(default=None, index=True)
    manual_requested_by: Optional[str] = Field(default=None, index=True)
    last_run_id: Optional[str] = Field(default=None, index=True)
    last_success_at: Optional[datetime] = Field(default=None, index=True)
    last_failure_at: Optional[datetime] = Field(default=None, index=True)
    next_scheduled_at: Optional[datetime] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
