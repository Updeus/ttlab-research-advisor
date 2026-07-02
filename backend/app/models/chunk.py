from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Chunk(SQLModel, table=True):
    chunk_id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paper.paper_id", index=True)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section: Optional[str] = None
    text: str
    token_count: Optional[int] = None
    embedding_status: str = "not_indexed"
    source_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
