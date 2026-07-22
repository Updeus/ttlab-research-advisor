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
        except (json.JSONDecodeError, TypeError) as exc:
            # Silently converting damaged persisted JSON to [] destroys the
            # distinction between "empty" and "corrupt" and can accidentally
            # publish or re-index incomplete records.  Fail loudly so the row
            # can be quarantined and repaired by an operator.
            raise ValueError("Malformed JSON persisted in a JSONEncodedValue column") from exc


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
    pdf_unavailability_reason: Optional[str] = Field(default=None, index=True)
    pdf_unavailability_detail: Optional[str] = None
    doi: Optional[str] = None
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    topics: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    all_urls: list[str] = Field(default_factory=list, sa_column=Column(JSONEncodedValue))
    raw_record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    ingestion_status: str = "discovered"
    pdf_text_status: str = "missing_pdf"
    extracted_json_path: Optional[str] = None
    extracted_text_path: Optional[str] = None
    # Immutable generation links for the source -> extraction -> chunks ->
    # public-index approval chain. Legacy rows remain fail closed until the
    # deterministic workers reconcile these fields.
    extraction_generation_id: Optional[str] = Field(default=None, index=True)
    extraction_input_pdf_sha256: Optional[str] = None
    extraction_config_sha256: Optional[str] = None
    chunk_extraction_generation_id: Optional[str] = Field(default=None, index=True)
    chunk_generation_id: Optional[str] = Field(default=None, index=True)
    public_index_generation_id: Optional[str] = Field(default=None, index=True)
    extraction_diagnostics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    extraction_content_type: str = Field(default="unknown", index=True)
    ocr_status: str = Field(default="not_requested", index=True)
    ocr_provider: Optional[str] = None
    ocr_provider_version: Optional[str] = None
    ocr_pages_count: int = 0
    ocr_review_required: bool = False
    metadata_provenance: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    metadata_field_reviews: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONEncodedValue))
    corpus_eligibility_status: str = Field(default="needs_review", index=True)
    corpus_exclusion_reason: Optional[str] = None
    # Editorial publication, redistribution rights, and technical corpus
    # eligibility are deliberately independent.  Legacy rows receive these
    # fail-closed defaults when the additive SQLite migration runs.
    publication_status: str = Field(default="pending_review", index=True)
    rights_status: str = Field(default="unknown", index=True)
    public_access_level: str = Field(default="hidden", index=True)
    pdf_title_match_status: str = Field(default="not_assessed", index=True)
    pdf_title_match_score: Optional[float] = None
    page_count: Optional[int] = None
    total_char_count: int = 0
    total_word_count: int = 0
    pages_with_text: int = 0
    pages_without_text: int = 0
    possible_scanned_pdf: bool = False
    chunk_count: int = 0
    review_status: str = "needs_review"
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    extraction_review_status: str = Field(default="needs_review", index=True)
    extraction_reviewer_notes: Optional[str] = None
    extraction_reviewed_at: Optional[datetime] = None
    extraction_reviewed_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
