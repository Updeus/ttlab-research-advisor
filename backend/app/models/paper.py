import json
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column, TypeDecorator, VARCHAR
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class JSONEncodedValue(TypeDecorator):
    impl = VARCHAR
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str:
        if value is None:
            return "[]"
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if not value:
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []


class Paper(SQLModel, table=True):
    paper_id: str = Field(primary_key=True)
    title: str = Field(index=True)
    authors: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    year: Optional[int] = Field(default=None, index=True)
    publication_date_raw: Optional[str] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    source_url: Optional[str] = None
    post_url: Optional[str] = Field(default=None, index=True)
    pdf_url: Optional[str] = None
    local_pdf_path: Optional[str] = None
    doi: Optional[str] = None
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    topics: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    all_urls: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    raw_record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    ingestion_status: str = "discovered"
    pdf_text_status: str = "missing_pdf"
    review_status: str = "needs_review"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
