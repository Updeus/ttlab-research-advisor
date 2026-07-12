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
    canonical_name: Optional[str] = Field(default=None, index=True)
    normalized_name: Optional[str] = Field(default=None, index=True)
    affiliation: Optional[str] = None
    email: Optional[str] = None
    profile_url: Optional[str] = None
    research_topics: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    paper_count: int = 0
    review_status: str = "needs_review"
    identity_status: str = Field(default="unresolved", index=True)
    identity_review_status: str = Field(default="needs_review", index=True)
    identity_review_notes: Optional[str] = None
    merged_into_author_id: Optional[int] = Field(default=None, foreign_key="author.id", index=True)
    persistent_identifier: Optional[str] = None
    persistent_identifier_source: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuthorAlias(SQLModel, table=True):
    alias_id: str = Field(primary_key=True)
    canonical_author_id: int = Field(foreign_key="author.id", index=True)
    alias: str = Field(index=True)
    normalized_alias: str = Field(index=True)
    source: str = "seed_import"
    review_status: str = Field(default="needs_review", index=True)
    reviewer_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
