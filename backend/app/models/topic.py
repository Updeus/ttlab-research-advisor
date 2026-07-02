from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class Topic(SQLModel, table=True):
    topic_id: str = Field(primary_key=True)
    name: str = Field(index=True)
    normalized_name: str = Field(index=True, unique=True)
    description: Optional[str] = None
    source: str = "deterministic_explorer"
    review_status: str = "needs_review"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PaperTopic(SQLModel, table=True):
    link_id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paper.paper_id", index=True)
    topic_id: str = Field(foreign_key="topic.topic_id", index=True)
    score: float = 0.0
    evidence_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    source: str = "deterministic_explorer"
    created_at: datetime = Field(default_factory=utc_now)


class AuthorTopic(SQLModel, table=True):
    link_id: str = Field(primary_key=True)
    author_id: int = Field(foreign_key="author.id", index=True)
    topic_id: str = Field(foreign_key="topic.topic_id", index=True)
    paper_count: int = 0
    score: float = 0.0
    evidence_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    created_at: datetime = Field(default_factory=utc_now)
