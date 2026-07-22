from datetime import UTC, datetime
from typing import Any, Optional

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
    generation_metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    runtime_provenance_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    claim_support_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    answerability_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    review_status: str = Field(default="needs_review", index=True)
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    citation_correct: Optional[bool] = None
    answer_faithfulness_score: Optional[int] = None
    usefulness_score: Optional[int] = None
    created_at: datetime = Field(default_factory=utc_now)
