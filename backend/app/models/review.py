import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column, DDL, event
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewEvent(SQLModel, table=True):
    review_event_id: str = Field(primary_key=True)
    item_type: str = Field(index=True)
    item_id: str = Field(index=True)
    action: str = Field(index=True)
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    reviewer_name: str = "Legacy unattributed actor"
    reviewer_id: str = Field(default="legacy-unattributed", index=True)
    reviewer_type: str = Field(default="unknown", index=True)
    reviewer_role: str = Field(default="unknown", index=True)
    request_id: str = Field(default="unavailable", index=True)
    reviewer_notes: Optional[str] = None
    diff_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    previous_event_hash: Optional[str] = None
    event_hash: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)

    @staticmethod
    def calculate_hash(
        *,
        review_event_id: str,
        previous_event_hash: Optional[str],
        item_type: str,
        item_id: str,
        action: str,
        previous_status: Optional[str],
        new_status: Optional[str],
        reviewer_id: str,
        reviewer_name: str,
        reviewer_type: str,
        reviewer_role: str,
        request_id: str,
        reviewer_notes: Optional[str],
        diff_json: dict[str, Any],
        created_at: datetime,
    ) -> str:
        payload = {
            "review_event_id": review_event_id,
            "previous_event_hash": previous_event_hash,
            "item_type": item_type,
            "item_id": item_id,
            "action": action,
            "previous_status": previous_status,
            "new_status": new_status,
            "reviewer_id": reviewer_id,
            "reviewer_name": reviewer_name,
            "reviewer_type": reviewer_type,
            "reviewer_role": reviewer_role,
            "request_id": request_id,
            "reviewer_notes": reviewer_notes,
            "diff_json": diff_json,
            "created_at": canonical_datetime(created_at),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReviewChainHead(SQLModel, table=True):
    """Singleton serialization point for the managed PostgreSQL review chain."""

    chain_id: int = Field(default=1, primary_key=True)
    review_event_id: Optional[str] = None
    event_hash: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)


PREVENT_REVIEW_EVENT_UPDATE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS prevent_review_event_update
    BEFORE UPDATE ON reviewevent
    BEGIN
        SELECT RAISE(ABORT, 'review events are append-only');
    END
    """
).execute_if(dialect="sqlite")

PREVENT_REVIEW_EVENT_DELETE = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS prevent_review_event_delete
    BEFORE DELETE ON reviewevent
    BEGIN
        SELECT RAISE(ABORT, 'review events are append-only');
    END
    """
).execute_if(dialect="sqlite")

event.listen(ReviewEvent.__table__, "after_create", PREVENT_REVIEW_EVENT_UPDATE)
event.listen(ReviewEvent.__table__, "after_create", PREVENT_REVIEW_EVENT_DELETE)


def canonical_datetime(value: datetime) -> str:
    """Canonicalize SQLite's naive UTC reload representation for hashing."""

    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")
