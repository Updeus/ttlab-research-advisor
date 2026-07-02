from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.paper import JSONEncodedValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class PaperArtifact(SQLModel, table=True):
    artifact_id: str = Field(primary_key=True)
    paper_id: str = Field(foreign_key="paper.paper_id", index=True)
    artifact_type: str = Field(index=True)
    generated_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    generated_text: str = ""
    source_chunk_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    citations_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    provider: str = "offline_deterministic"
    model: str = "paper-artifact-template-v1"
    generation_status: str = Field(default="generated", index=True)
    grounding_status: str = Field(default="unsupported", index=True)
    review_status: str = Field(default="needs_review", index=True)
    warnings_json: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
