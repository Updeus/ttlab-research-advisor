from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class Author(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    affiliation: Optional[str] = None
    email: Optional[str] = None
    profile_url: Optional[str] = None
    research_topics: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    paper_count: int = 0
    review_status: str = "needs_review"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
