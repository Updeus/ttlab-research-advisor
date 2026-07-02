from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column
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
    reviewer_name: str = "local_admin"
    reviewer_notes: Optional[str] = None
    diff_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    created_at: datetime = Field(default_factory=utc_now, index=True)
