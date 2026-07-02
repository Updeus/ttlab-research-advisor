from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class RAGAnswer(SQLModel, table=True):
    answer_id: str = Field(primary_key=True)
    question: str = Field(index=True)
    answer: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    cited_paper_ids: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    citations_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    retrieval_mode: str = "hybrid"
    top_k: int = 5
    provider: str = "offline_extractive"
    model: str = "sentence-overlap-v1"
    grounding_status: str = "unsupported"
    unsupported_claims_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    warnings_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    retrieved_chunks_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    created_at: datetime = Field(default_factory=utc_now)
