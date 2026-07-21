from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Chunk(SQLModel, table=True):
    chunk_id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paper.paper_id", index=True)
    chunk_index: int = Field(default=0, index=True)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section: Optional[str] = None
    text: str
    char_count: int = 0
    word_count: int = 0
    token_count: Optional[int] = None
    token_count_estimate: Optional[int] = None
    embedding_status: str = "not_indexed"
    source_hash: Optional[str] = None
    extraction_generation_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
