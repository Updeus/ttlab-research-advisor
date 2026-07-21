from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class ThesisRecommendation(SQLModel, table=True):
    recommendation_id: str = Field(primary_key=True)
    request_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    student_interests_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    student_skills_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    available_time: str = Field(index=True)
    project_type: str = Field(index=True)
    data_constraints: str = ""
    preferred_difficulty: str = Field(index=True)
    recommendations_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    provider: str = "offline_deterministic"
    model: str = "template-recommender-v1"
    retrieval_mode: str = "hybrid"
    top_k: int = 5
    grounding_status: str = Field(default="unsupported", index=True)
    warnings_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    runtime_provenance_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    review_status: str = Field(default="needs_review", index=True)
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    corrected_recommendations_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    correction_grounding_status: str = Field(default="not_applicable", index=True)
    correction_source_chunk_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    correction_citations_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    correction_runtime_provenance_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    created_at: datetime = Field(default_factory=utc_now)
