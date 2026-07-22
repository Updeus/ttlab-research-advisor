from __future__ import annotations

import json
import hashlib
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, desc, func, select

from app.config import Settings, get_settings
from app.db import get_session, sqlite_integrity_diagnostics
from app.ingestion.sync import ATOMIC_GENERATION_PROMOTION_IMPLEMENTED, ingestion_sync_status, request_manual_sync
from app.ingestion.manual_import import (
    invalidate_generated_outputs_for_paper,
    invalidate_paper_descendants,
    reset_dependent_graph_reviews_for_paper,
)
from app.ingestion.metadata_cleaner import clean_author_name, is_malformed_author_name, normalize_author_key
from app.intelligence.paper_artifact_generator import (
    artifact_correction_blockers,
    canonicalize_artifact_correction,
)
from app.intelligence.extension_recommender import (
    canonicalize_recommendation_correction,
    recommendation_correction_blockers,
)
from app.intelligence.topic_explorer import normalize_topic
from app.models import (
    Author,
    AuthorAlias,
    AuthorTopic,
    Chunk,
    Paper,
    PaperArtifact,
    PaperTopic,
    RAGAnswer,
    ReviewEvent,
    ThesisRecommendation,
    Topic,
)
from app.publication import (
    PUBLIC_ACCESS_LEVELS,
    PUBLICATION_STATUSES,
    RIGHTS_STATUSES,
    content_generation_diagnostics,
    publication_state,
)
from app.security import AuthenticatedActor, operational_boundary_diagnostics, require_admin, require_reviewer

try:
    import fcntl
except ImportError:  # pragma: no cover - unsupported deployment is rejected at runtime
    fcntl = None  # type: ignore[assignment]

# FastAPI may enter and exit a synchronous generator dependency on different
# worker threads. A primitive Lock is intentionally not thread-owned, whereas
# RLock would raise when cleanup runs on a different worker.
_ADMIN_REVIEW_THREAD_LOCK = threading.Lock()


def admin_review_lock_path(settings: Settings) -> Path:
    """Return a runtime-owned, database-scoped review-chain lock path."""

    directory = settings.admin_review_lock_dir
    if not directory.is_absolute():
        directory = settings.project_root / directory
    if directory.is_symlink():
        raise HTTPException(status_code=503, detail="Review lock directory may not be a symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise HTTPException(status_code=503, detail="Review lock directory may not be a symlink")
    database_scope = hashlib.sha256(settings.database_url.encode("utf-8")).hexdigest()[:24]
    return directory / f"review-chain-{database_scope}.lock"


@contextmanager
def admin_review_lock(settings: Settings):  # type: ignore[no-untyped-def]
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        raise HTTPException(status_code=503, detail="Safe cross-process review-event locking is unavailable")
    lock_path = admin_review_lock_path(settings)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    lock_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_descriptor: int | None = None
    try:
        # Resolve the final name relative to an already-opened, non-symlink
        # directory. O_NOFOLLOW on only the final lock filename would still
        # permit an attacker to exchange an intermediate directory after the
        # path checks above.
        directory_descriptor = os.open(lock_path.parent, directory_flags)
        os.fchmod(directory_descriptor, 0o700)
        descriptor = os.open(lock_path.name, lock_flags, 0o600, dir_fd=directory_descriptor)
    except OSError as exc:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise HTTPException(status_code=503, detail="Review-event lock could not be opened safely") from exc
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+b", closefd=False) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def serialize_admin_review_requests(
    settings: Annotated[Settings, Depends(get_settings)],
):  # type: ignore[no-untyped-def]
    """Hold a process and database-scoped lock across read/mutate/hash/commit."""

    with _ADMIN_REVIEW_THREAD_LOCK:
        with admin_review_lock(settings):
            yield

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_reviewer), Depends(serialize_admin_review_requests)],
)

ReviewStatus = Literal["needs_review", "ai_reviewed", "reviewed", "approved", "rejected", "needs_reprocess"]

REVIEWABLE_ITEM_TYPES = {
    "author",
    "author_alias",
    "author_topic",
    "paper",
    "paper_topic",
    "rag_answer",
    "thesis_recommendation",
    "paper_artifact",
    "topic",
}


class PaperPatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    authors: Optional[list[str]] = Field(default=None, max_length=100)
    year: Optional[int] = Field(default=None, ge=1800, le=2200)
    publication_date_raw: Optional[str] = Field(default=None, max_length=100)
    venue: Optional[str] = Field(default=None, max_length=500)
    topics: Optional[list[str]] = Field(default=None, max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=2_048)
    pdf_url: Optional[str] = Field(default=None, max_length=2_048)
    abstract: Optional[str] = Field(default=None, max_length=50_000)
    doi: Optional[str] = Field(default=None, max_length=255)
    keywords: Optional[list[str]] = Field(default=None, max_length=100)
    review_status: Optional[ReviewStatus] = None
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)

    @field_validator("source_url", "pdf_url")
    @classmethod
    def web_urls_only(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("URL must be an http(s) URL without embedded credentials")
        return value

    @field_validator("authors", "topics", "keywords")
    @classmethod
    def bounded_text_items(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        normalized = [value.strip() for value in values if value.strip()]
        if any(len(value) > 300 for value in normalized):
            raise ValueError("List items may not exceed 300 characters")
        return normalized


class ArtifactReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class ArtifactCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_text: Optional[str] = Field(default=None, max_length=250_000)
    corrected_json: Optional[dict[str, Any]] = None
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class PublicationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_status: Literal["pending_review", "published", "hidden"]
    rights_status: Literal["unknown", "cleared", "restricted"]
    public_access_level: Literal["hidden", "metadata_only", "searchable"]
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class RecommendationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class RecommendationCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_recommendations_json: Optional[dict[str, Any] | list[dict[str, Any]]] = None
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


def validate_correction_json_limits(value: Any) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Correction payload must be finite JSON") from exc
    if len(encoded.encode("utf-8")) > 500_000:
        raise HTTPException(status_code=422, detail="Correction payload exceeds the 500000-byte limit")
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 10 or nodes > 10_000:
            raise HTTPException(status_code=422, detail="Correction payload is too deeply nested or complex")
        if isinstance(item, dict):
            if any(not isinstance(key, str) or len(key) > 200 for key in item):
                raise HTTPException(status_code=422, detail="Correction object keys must be bounded strings")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str) and len(item) > 250_000:
            raise HTTPException(status_code=422, detail="Correction string value is too long")

    visit(value, 0)


def correction_provenance(actor: AuthenticatedActor) -> dict[str, Any]:
    return {
        "source": "reviewer_correction",
        "evidence_verification": "not_performed",
        "original_generated_evidence_inherited": False,
        "reviewer_type": actor.reviewer_type,
        "reviewer_role": actor.role,
        "recorded_at": utc_now().isoformat(),
    }


class AnswerReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)
    citation_correct: Optional[bool] = None
    answer_faithfulness_score: Optional[int] = Field(default=None, ge=1, le=5)
    usefulness_score: Optional[int] = Field(default=None, ge=1, le=5)


class ExtractionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class GraphReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class AuthorCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    canonical_name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    affiliation: Optional[str] = Field(default=None, max_length=500)
    email: Optional[str] = Field(default=None, max_length=320)
    profile_url: Optional[str] = Field(default=None, max_length=2_048)
    persistent_identifier: Optional[str] = Field(default=None, max_length=255)
    persistent_identifier_source: Optional[str] = Field(default=None, max_length=100)
    identity_status: Optional[Literal["unresolved", "ambiguous", "resolved", "merged", "invalid"]] = None
    merged_into_author_id: Optional[int] = Field(default=None, ge=1)
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)

    @field_validator("profile_url")
    @classmethod
    def profile_url_must_be_web_url(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("profile_url must be an http(s) URL without embedded credentials")
        return value


class AuthorAliasCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    alias: Optional[str] = Field(default=None, min_length=1, max_length=300)
    canonical_author_id: Optional[int] = Field(default=None, ge=1)
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class TopicCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4_000)
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class PaperTopicCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Optional[float] = Field(default=None, ge=0.0)
    evidence_json: Optional[list[dict[str, Any]]] = Field(default=None, max_length=100)
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


class AuthorTopicCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_count: Optional[int] = Field(default=None, ge=0)
    score: Optional[float] = Field(default=None, ge=0.0)
    evidence_json: Optional[list[dict[str, Any]]] = Field(default=None, max_length=100)
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


@router.get("/ingestion-sync")
def get_ingestion_sync(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    return {
        **ingestion_sync_status(session, settings),
        "manual_trigger_allowed": bool(
            actor.role == "admin"
            and settings.sync_enabled
        ),
    }


@router.post("/ingestion-sync/request", status_code=202)
def request_ingestion_sync(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, Any]:
    if not settings.sync_enabled:
        raise HTTPException(
            status_code=409,
            detail="TTLAB discovery checks are disabled until TTLAB_SYNC_ENABLED=true and the isolated worker is running",
        )
    _state, accepted = request_manual_sync(session, actor.actor_id)
    return {
        "accepted": accepted,
        "message": "TTLAB discovery check queued for the isolated ingestion worker."
        if accepted
        else "A manual synchronization request is already pending.",
        "sync": {
            **ingestion_sync_status(session, settings),
            "manual_trigger_allowed": True,
        },
    }


@router.get("/overview")
def admin_overview(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    papers = list(session.exec(select(Paper)).all())
    answers = list(session.exec(select(RAGAnswer)).all())
    recommendations = list(session.exec(select(ThesisRecommendation)).all())
    artifacts = list(session.exec(select(PaperArtifact)).all())
    recent_events = list(
        session.exec(select(ReviewEvent).order_by(desc(ReviewEvent.created_at)).limit(10)).all()
    )
    all_events = list(
        session.exec(select(ReviewEvent).order_by(ReviewEvent.created_at, ReviewEvent.review_event_id)).all()
    )
    return {
        "papers_total": len(papers),
        "papers_needing_metadata_review": sum(1 for paper in papers if paper.review_status == "needs_review"),
        "papers_missing_pdfs": sum(1 for paper in papers if paper.pdf_text_status == "missing_pdf"),
        "papers_with_extraction_failures": sum(
            1
            for paper in papers
            if paper.pdf_text_status in {
                "extraction_failed",
                "download_failed",
                "invalid_pdf",
                "no_text",
                "scanned_pdf",
                "blank_pdf",
            }
        ),
        "possible_scanned_pdfs": sum(1 for paper in papers if paper.possible_scanned_pdf),
        "ocr_review_required": sum(1 for paper in papers if paper.ocr_review_required),
        "pdf_unavailability_reasons": count_by_attr(
            [paper for paper in papers if paper.pdf_unavailability_reason],
            "pdf_unavailability_reason",
        ),
        "total_chunks": session.exec(select(func.count()).select_from(Chunk)).one(),
        "rag_answers": status_breakdown(answers),
        "rag_answers_by_grounding": grounding_breakdown(answers),
        "thesis_recommendations": status_breakdown(recommendations),
        "thesis_recommendations_by_grounding": grounding_breakdown(recommendations),
        "paper_artifacts": status_breakdown(artifacts),
        "paper_artifacts_by_grounding": grounding_breakdown(artifacts),
        "paper_artifacts_by_type": count_by_attr(artifacts, "artifact_type"),
        "artifacts_needing_review": sum(1 for artifact in artifacts if artifact.review_status == "needs_review"),
        "total_review_events": session.exec(select(func.count()).select_from(ReviewEvent)).one(),
        "review_event_integrity": verify_review_event_chain(all_events),
        "recent_review_events": [serialize_review_event(event) for event in recent_events],
        "database_integrity": sqlite_integrity_diagnostics(session.get_bind()),
        "operational_boundaries": operational_boundary_diagnostics(settings),
    }


@router.get("/capabilities")
def actor_capabilities(
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Describe permissions and transitions so clients do not guess policy."""

    statuses = ["needs_review", "ai_reviewed", "reviewed", "approved", "rejected", "needs_reprocess"]
    transitions: dict[str, list[str]] = {}
    for previous in statuses:
        transitions[previous] = [
            target for target in statuses if transition_allowed(previous, target, actor)
        ]
    return {
        "actor": {
            "actor_id": actor.actor_id,
            "role": actor.role,
            "reviewer_type": actor.reviewer_type,
            "local_demo_bypass": actor.local_demo_bypass,
        },
        "capabilities": {
            "review": True,
            "save_corrections": True,
            "approve_or_reject": actor.role == "admin" and actor.reviewer_type == "human",
            "set_publication_and_rights": actor.role == "admin" and actor.reviewer_type == "human",
            "trigger_ingestion": bool(
                actor.role == "admin"
                and settings.sync_enabled
            ),
        },
        "allowed_review_transitions": transitions,
    }


@router.get("/publication-preview/papers")
def publication_preview(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    papers = list(session.exec(select(Paper).order_by(Paper.title, Paper.paper_id)).all())
    return {
        "surface": "local_review_preview",
        "public": False,
        "notice": "REVIEW PREVIEW — records shown here are not necessarily approved for public display or redistribution.",
        "items": [serialize_paper_for_admin(session, paper) for paper in papers],
    }


@router.get("/publication-preview/papers/{paper_id}")
def publication_preview_detail(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    chunks = session.exec(
        select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.chunk_index)
    ).all()
    artifacts = session.exec(
        select(PaperArtifact)
        .where(PaperArtifact.paper_id == paper_id)
        .order_by(PaperArtifact.artifact_type, desc(PaperArtifact.created_at))
    ).all()
    return {
        "surface": "local_review_preview",
        "public": False,
        "notice": "REVIEW PREVIEW — source text and drafts on this route are never public output.",
        "paper": serialize_paper_for_admin(session, paper),
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "section": chunk.section,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "text": chunk.text,
            }
            for chunk in chunks
        ],
        "artifacts": [serialize_artifact_for_admin(artifact) for artifact in artifacts],
    }


@router.get("/review-queue")
def review_queue(
    session: Annotated[Session, Depends(get_session)],
    item_type: Optional[str] = Query(default=None, max_length=100),
    review_status: Optional[str] = Query(default="needs_review", max_length=100),
    grounding_status: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if item_type and item_type not in REVIEWABLE_ITEM_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported item_type")
    items: list[dict[str, Any]] = []
    if item_type in {None, "author"}:
        items.extend(author_queue_items(session, review_status))
    if item_type in {None, "author_alias"}:
        items.extend(author_alias_queue_items(session, review_status))
    if item_type in {None, "topic"}:
        items.extend(topic_queue_items(session, review_status))
    if item_type in {None, "paper_topic"}:
        items.extend(paper_topic_queue_items(session, review_status))
    if item_type in {None, "author_topic"}:
        items.extend(author_topic_queue_items(session, review_status))
    if item_type in {None, "paper"}:
        items.extend(paper_queue_items(session, review_status))
    if item_type in {None, "rag_answer"}:
        items.extend(answer_queue_items(session, review_status, grounding_status))
    if item_type in {None, "thesis_recommendation"}:
        items.extend(recommendation_queue_items(session, review_status, grounding_status))
    if item_type in {None, "paper_artifact"}:
        items.extend(artifact_queue_items(session, review_status, grounding_status))
    items.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    total = len(items)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items[offset : offset + limit],
    }


@router.patch("/papers/{paper_id}")
def patch_paper(
    paper_id: str,
    request: PaperPatchRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    previous_status = paper.review_status
    updates = request.model_dump(exclude_unset=True)
    corrected_metadata_fields = {
        field_name
        for field_name, new_value in updates.items()
        if field_name not in {"review_status", "reviewer_notes"}
        and getattr(paper, field_name) != new_value
    }
    if corrected_metadata_fields:
        # A correction creates a new reviewable version. It cannot inherit or
        # acquire approval in the same operation, even when an administrator
        # submitted the previous/final status again.
        updates["review_status"] = "needs_review"
    if "review_status" in updates:
        enforce_review_transition(previous_status, str(updates["review_status"]), actor)
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        old_value = getattr(paper, field_name)
        if old_value != new_value:
            diff[field_name] = {"before": old_value, "after": new_value}
            setattr(paper, field_name, new_value)
    if corrected_metadata_fields:
        provenance = dict(paper.metadata_provenance or {})
        field_reviews = dict(paper.metadata_field_reviews or {})
        for field_name in corrected_metadata_fields:
            provenance[field_name] = {
                "source": "admin_review",
                "reviewer_id": actor.actor_id,
                "reviewer_type": actor.reviewer_type,
                "reviewer_role": actor.role,
                "recorded_at": utc_now().isoformat(),
                "status": "needs_review",
            }
            field_reviews[field_name] = "needs_review"
        paper.metadata_provenance = provenance
        paper.metadata_field_reviews = field_reviews
        # Metadata correction creates a new unpublished version. A separate,
        # attributable human-admin publication decision is required after the
        # corrected metadata is approved.
        update_if_changed(paper, "publication_status", "pending_review", diff)
        update_if_changed(paper, "public_access_level", "hidden", diff)
        dependent_resets = reset_dependent_graph_reviews_for_paper(
            session,
            paper.paper_id,
            reason="Paper metadata correction requires topic-link re-review.",
        )
        diff["dependent_graph_reviews_reset"] = {"before": None, "after": dependent_resets}
        generated_resets = invalidate_generated_outputs_for_paper(
            session,
            paper.paper_id,
            reason="Paper metadata correction requires generated-output regeneration and re-review.",
        )
        diff["dependent_generated_outputs_reset"] = {"before": None, "after": generated_resets}
        if corrected_metadata_fields.intersection({"title", "source_url", "pdf_url"}):
            prior_local_path = paper.local_pdf_path
            source_identity_changed = bool(
                corrected_metadata_fields.intersection({"source_url", "pdf_url"})
            )
            retain_local_path = None if source_identity_changed else prior_local_path
            invalidate_paper_descendants(
                session,
                paper,
                retained_local_pdf_path=retain_local_path,
                reason=(
                    "title_change_requires_pdf_identity_reaudit"
                    if not source_identity_changed
                    else "admin_source_change_requires_reprocessing"
                ),
            )
    if "review_status" in updates or "reviewer_notes" in updates:
        apply_review_metadata(paper, paper.review_status, request.reviewer_notes, actor)
    paper.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper",
        item_id=paper.paper_id,
        action=action_for_status(paper.review_status, corrected=bool(corrected_metadata_fields)),
        previous_status=previous_status,
        new_status=paper.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(paper)
    session.add(event)
    session.commit()
    session.refresh(paper)
    return {"paper": paper, "review_event": serialize_review_event(event)}


@router.patch("/papers/{paper_id}/publication")
def decide_paper_publication(
    paper_id: str,
    request: PublicationDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, Any]:
    if actor.reviewer_type != "human":
        raise HTTPException(status_code=403, detail="Publication and rights decisions require a human admin")
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    if request.publication_status == "published" and paper.review_status != "approved":
        raise HTTPException(status_code=409, detail="Paper metadata must be approved before publication")
    if request.public_access_level != "hidden" and (
        request.publication_status != "published" or request.rights_status != "cleared"
    ):
        raise HTTPException(
            status_code=409,
            detail="Public access requires both published editorial status and cleared rights",
        )
    if request.public_access_level == "searchable" and paper.corpus_eligibility_status != "eligible":
        raise HTTPException(status_code=409, detail="Search access requires an eligible technical corpus record")
    if request.public_access_level == "searchable" and paper.extraction_review_status != "approved":
        raise HTTPException(status_code=409, detail="Search access requires an approved extraction review")
    if request.public_access_level == "searchable":
        generation = content_generation_diagnostics(session, paper)
        if not generation["ready"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "content_generation_not_ready",
                    "blockers": generation["blockers"],
                },
            )
        from app.indexing.embedder import DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER, index_diagnostics
        from app.indexing.keyword_search import diagnostics as keyword_index_diagnostics

        index_states = {
            "keyword": keyword_index_diagnostics(session).get("status"),
            "feature_hashing": index_diagnostics(
                session,
                DEFAULT_INDEX_PATH,
                FEATURE_HASHING_PROVIDER,
            ).get("status"),
        }
        if any(status != "ready" for status in index_states.values()):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "content_index_not_ready",
                    "index_states": index_states,
                },
            )
    diff: dict[str, dict[str, Any]] = {}
    for field_name in ("publication_status", "rights_status", "public_access_level"):
        update_if_changed(paper, field_name, getattr(request, field_name), diff)
    update_if_changed(
        paper,
        "public_index_generation_id",
        paper.chunk_generation_id if request.public_access_level == "searchable" else None,
        diff,
    )
    if not diff:
        return {"paper": serialize_paper_for_admin(session, paper), "review_event": None}
    paper.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper_publication",
        item_id=paper.paper_id,
        action="publication_decision",
        previous_status=None,
        new_status=paper.publication_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(paper)
    session.add(event)
    session.commit()
    session.refresh(paper)
    return {"paper": serialize_paper_for_admin(session, paper), "review_event": serialize_review_event(event)}


@router.patch("/artifacts/{artifact_id}/review")
def review_artifact(
    artifact_id: str,
    request: ArtifactReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    artifact = session.get(PaperArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    previous_status = artifact.review_status
    target_status = request.review_status
    enforce_review_transition(previous_status, target_status, actor)
    if target_status == "approved":
        blockers = artifact_correction_blockers(artifact)
        if blockers:
            raise HTTPException(
                status_code=409,
                detail={"code": "artifact_correction_inconsistent", "blockers": blockers},
            )
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(artifact, "review_status", target_status, diff)
    update_if_changed(artifact, "reviewer_notes", request.reviewer_notes, diff)
    apply_review_metadata(artifact, target_status, request.reviewer_notes, actor)
    artifact.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper_artifact",
        item_id=artifact.artifact_id,
        action=action_for_status(target_status, corrected=False),
        previous_status=previous_status,
        new_status=target_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(artifact)
    session.add(event)
    session.commit()
    session.refresh(artifact)
    return {"artifact": serialize_artifact_for_admin(artifact), "review_event": serialize_review_event(event)}


@router.patch("/artifacts/{artifact_id}/correction")
def save_artifact_correction(
    artifact_id: str,
    request: ArtifactCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    artifact = session.get(PaperArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if request.corrected_text is None and request.corrected_json is None:
        raise HTTPException(status_code=422, detail="A corrected_text or corrected_json value is required")
    if request.corrected_json is not None:
        validate_correction_json_limits(request.corrected_json)
    try:
        canonical_json, derived_text = canonicalize_artifact_correction(
            artifact,
            corrected_json=request.corrected_json,
            corrected_text=request.corrected_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    previous_status = artifact.review_status
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(artifact, "corrected_json", canonical_json, diff)
    update_if_changed(artifact, "corrected_text", derived_text, diff)
    update_if_changed(artifact, "review_status", "needs_review", diff)
    update_if_changed(artifact, "correction_grounding_status", "unsupported", diff)
    update_if_changed(artifact, "correction_source_chunk_ids_json", [], diff)
    update_if_changed(artifact, "correction_citations_json", [], diff)
    if not diff:
        return {"artifact": serialize_artifact_for_admin(artifact), "review_event": None}
    update_if_changed(artifact, "correction_runtime_provenance_json", correction_provenance(actor), diff)
    apply_review_metadata(artifact, "needs_review", request.reviewer_notes, actor)
    artifact.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper_artifact",
        item_id=artifact.artifact_id,
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(artifact)
    session.add(event)
    session.commit()
    session.refresh(artifact)
    return {"artifact": serialize_artifact_for_admin(artifact), "review_event": serialize_review_event(event)}


@router.patch("/recommendations/{recommendation_id}/review")
def review_recommendation(
    recommendation_id: str,
    request: RecommendationReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    recommendation = session.get(ThesisRecommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    previous_status = recommendation.review_status
    target_status = request.review_status
    enforce_review_transition(previous_status, target_status, actor)
    if target_status == "approved":
        blockers = recommendation_correction_blockers(recommendation)
        if blockers:
            raise HTTPException(
                status_code=409,
                detail={"code": "recommendation_correction_inconsistent", "blockers": blockers},
            )
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(recommendation, "review_status", target_status, diff)
    update_if_changed(recommendation, "reviewer_notes", request.reviewer_notes, diff)
    apply_review_metadata(recommendation, target_status, request.reviewer_notes, actor)
    event = create_review_event(
        session,
        item_type="thesis_recommendation",
        item_id=recommendation.recommendation_id,
        action=action_for_status(target_status, corrected=False),
        previous_status=previous_status,
        new_status=target_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(recommendation)
    session.add(event)
    session.commit()
    session.refresh(recommendation)
    return {"recommendation": serialize_recommendation_for_admin(recommendation), "review_event": serialize_review_event(event)}


@router.patch("/recommendations/{recommendation_id}/correction")
def save_recommendation_correction(
    recommendation_id: str,
    request: RecommendationCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    recommendation = session.get(ThesisRecommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if request.corrected_recommendations_json is None:
        raise HTTPException(status_code=422, detail="corrected_recommendations_json is required")
    normalized_correction = (
        {"items": request.corrected_recommendations_json}
        if isinstance(request.corrected_recommendations_json, list)
        else request.corrected_recommendations_json
    )
    validate_correction_json_limits(normalized_correction)
    try:
        canonical_correction = canonicalize_recommendation_correction(normalized_correction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    previous_status = recommendation.review_status
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(
        recommendation,
        "corrected_recommendations_json",
        canonical_correction,
        diff,
    )
    update_if_changed(recommendation, "review_status", "needs_review", diff)
    update_if_changed(recommendation, "correction_grounding_status", "unsupported", diff)
    update_if_changed(recommendation, "correction_source_chunk_ids_json", [], diff)
    update_if_changed(recommendation, "correction_citations_json", [], diff)
    if not diff:
        return {"recommendation": serialize_recommendation_for_admin(recommendation), "review_event": None}
    update_if_changed(
        recommendation,
        "correction_runtime_provenance_json",
        correction_provenance(actor),
        diff,
    )
    apply_review_metadata(recommendation, "needs_review", request.reviewer_notes, actor)
    event = create_review_event(
        session,
        item_type="thesis_recommendation",
        item_id=recommendation.recommendation_id,
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(recommendation)
    session.add(event)
    session.commit()
    session.refresh(recommendation)
    return {"recommendation": serialize_recommendation_for_admin(recommendation), "review_event": serialize_review_event(event)}


@router.patch("/answers/{answer_id}/review")
def review_answer(
    answer_id: str,
    request: AnswerReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    answer = session.get(RAGAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    previous_status = answer.review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    for field_name in (
        "review_status",
        "reviewer_notes",
        "citation_correct",
        "answer_faithfulness_score",
        "usefulness_score",
    ):
        if field_name in request.model_fields_set:
            update_if_changed(answer, field_name, getattr(request, field_name), diff)
    apply_review_metadata(answer, request.review_status, request.reviewer_notes, actor)
    event = create_review_event(
        session,
        item_type="rag_answer",
        item_id=answer.answer_id,
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(answer)
    session.add(event)
    session.commit()
    session.refresh(answer)
    return {"answer": serialize_answer_for_admin(answer), "review_event": serialize_review_event(event)}


@router.patch("/extraction/{paper_id}/review")
def review_extraction(
    paper_id: str,
    request: ExtractionReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    previous_status = paper.extraction_review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(paper, "extraction_review_status", request.review_status, diff)
    update_if_changed(paper, "extraction_reviewer_notes", request.reviewer_notes, diff)
    paper.extraction_reviewed_at = utc_now()
    paper.extraction_reviewed_by = actor.actor_id
    paper.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="extraction",
        item_id=paper.paper_id,
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(paper)
    session.add(event)
    session.commit()
    session.refresh(paper)
    return {"paper": serialize_paper_for_admin(session, paper), "review_event": serialize_review_event(event)}


@router.patch("/authors/{author_id}/review")
def review_author(
    author_id: int,
    request: GraphReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    author = session.get(Author, author_id)
    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")
    previous_status = author.identity_review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    if request.review_status == "approved":
        raise_if_approval_blocked("author", author_approval_blockers(session, author))
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(author, "identity_review_status", request.review_status, diff)
    update_if_changed(author, "review_status", request.review_status, diff)
    update_if_changed(author, "identity_review_notes", request.reviewer_notes, diff)
    author.identity_reviewed_at = utc_now()
    author.identity_reviewed_by = actor.actor_id
    author.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="author",
        item_id=str(author_id),
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(author)
    session.add(event)
    session.commit()
    session.refresh(author)
    return {"author": serialize_author_for_admin(session, author), "review_event": serialize_review_event(event)}


@router.patch("/authors/{author_id}/correction")
def save_author_correction(
    author_id: int,
    request: AuthorCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    author = session.get(Author, author_id)
    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")
    updates = request.model_dump(exclude_unset=True)
    notes = updates.pop("reviewer_notes", None)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one author correction field is required")

    requested_status = str(updates.get("identity_status", author.identity_status))
    requested_target = updates.get("merged_into_author_id", author.merged_into_author_id)
    if requested_status == "merged":
        if requested_target is None:
            raise HTTPException(status_code=409, detail="A merged identity requires merged_into_author_id")
        if requested_target == author_id:
            raise HTTPException(status_code=409, detail="An author identity cannot merge into itself")
        target = session.get(Author, requested_target)
        if target is None or target.identity_status in {"merged", "invalid"}:
            raise HTTPException(status_code=409, detail="Merge target must be an active author identity")
    elif "merged_into_author_id" in updates and requested_target is not None:
        raise HTTPException(status_code=409, detail="merged_into_author_id is only valid for a merged identity")

    if "canonical_name" in updates:
        canonical_name = updates["canonical_name"]
        if canonical_name is None or is_malformed_author_name(canonical_name):
            raise HTTPException(status_code=422, detail="canonical_name must be a valid author name")
        cleaned_name = clean_author_name(canonical_name)
        normalized_name = normalize_author_key(cleaned_name)
        collision = session.exec(
            select(Author)
            .where(Author.normalized_name == normalized_name)
            .where(Author.id != author_id)
            .where(Author.identity_status.notin_(["merged", "invalid"]))
        ).first()
        if collision is not None and requested_status != "merged":
            raise HTTPException(
                status_code=409,
                detail="canonical_name already belongs to another active identity; record an explicit merge instead",
            )
        updates["canonical_name"] = cleaned_name
        updates["normalized_name"] = normalized_name
    if requested_status != "merged" and author.merged_into_author_id is not None:
        updates["merged_into_author_id"] = None

    previous_status = author.identity_review_status
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        update_if_changed(author, field_name, new_value, diff)
    if not diff:
        return {"author": serialize_author_for_admin(session, author), "review_event": None}
    update_if_changed(author, "identity_review_status", "needs_review", diff)
    update_if_changed(author, "review_status", "needs_review", diff)
    update_if_changed(author, "identity_review_notes", notes, diff)
    if {"canonical_name", "normalized_name", "identity_status", "merged_into_author_id"}.intersection(diff):
        dependent_resets = reset_author_topic_reviews(
            session,
            {author_id},
            reason="Author identity correction requires topic-link re-review.",
        )
        diff["dependent_author_topic_reviews_reset"] = {"before": None, "after": dependent_resets}
    author.identity_reviewed_at = utc_now()
    author.identity_reviewed_by = actor.actor_id
    author.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="author",
        item_id=str(author_id),
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=notes,
        diff=diff,
        actor=actor,
    )
    session.add(author)
    session.add(event)
    session.commit()
    session.refresh(author)
    return {"author": serialize_author_for_admin(session, author), "review_event": serialize_review_event(event)}


@router.patch("/author-aliases/{alias_id}/review")
def review_author_alias(
    alias_id: str,
    request: GraphReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    alias = session.get(AuthorAlias, alias_id)
    if alias is None:
        raise HTTPException(status_code=404, detail="Author alias not found")
    previous_status = alias.review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    if request.review_status == "approved":
        raise_if_approval_blocked("author_alias", author_alias_approval_blockers(session, alias))
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(alias, "review_status", request.review_status, diff)
    apply_review_metadata(alias, request.review_status, request.reviewer_notes, actor)
    alias.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="author_alias",
        item_id=alias.alias_id,
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(alias)
    session.add(event)
    session.commit()
    session.refresh(alias)
    return {"author_alias": serialize_author_alias_for_admin(session, alias), "review_event": serialize_review_event(event)}


@router.patch("/author-aliases/{alias_id}/correction")
def save_author_alias_correction(
    alias_id: str,
    request: AuthorAliasCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    alias = session.get(AuthorAlias, alias_id)
    if alias is None:
        raise HTTPException(status_code=404, detail="Author alias not found")
    prior_author_id = alias.canonical_author_id
    updates = request.model_dump(exclude_unset=True)
    notes = updates.pop("reviewer_notes", None)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one alias correction field is required")
    if "canonical_author_id" in updates and session.get(Author, updates["canonical_author_id"]) is None:
        raise HTTPException(status_code=409, detail="canonical_author_id does not identify an existing author")
    if "alias" in updates:
        raw_alias = updates["alias"]
        if raw_alias is None or is_malformed_author_name(raw_alias):
            raise HTTPException(status_code=422, detail="alias must be a valid author name")
        cleaned_alias = clean_author_name(raw_alias)
        normalized_alias = normalize_author_key(cleaned_alias)
        target_id = int(updates.get("canonical_author_id", alias.canonical_author_id))
        collision = session.exec(
            select(AuthorAlias)
            .where(AuthorAlias.normalized_alias == normalized_alias)
            .where(AuthorAlias.alias_id != alias_id)
        ).first()
        if collision is not None and collision.canonical_author_id != target_id:
            raise HTTPException(status_code=409, detail="Alias is already assigned to another author identity")
        updates["alias"] = cleaned_alias
        updates["normalized_alias"] = normalized_alias
    previous_status = alias.review_status
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        update_if_changed(alias, field_name, new_value, diff)
    if not diff:
        return {"author_alias": serialize_author_alias_for_admin(session, alias), "review_event": None}
    update_if_changed(alias, "review_status", "needs_review", diff)
    apply_review_metadata(alias, "needs_review", notes, actor)
    if {"alias", "normalized_alias", "canonical_author_id"}.intersection(diff):
        dependent_resets = reset_author_topic_reviews(
            session,
            {prior_author_id, alias.canonical_author_id},
            reason="Author alias correction requires topic-link re-review.",
        )
        diff["dependent_author_topic_reviews_reset"] = {"before": None, "after": dependent_resets}
    alias.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="author_alias",
        item_id=alias.alias_id,
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=notes,
        diff=diff,
        actor=actor,
    )
    session.add(alias)
    session.add(event)
    session.commit()
    session.refresh(alias)
    return {"author_alias": serialize_author_alias_for_admin(session, alias), "review_event": serialize_review_event(event)}


@router.patch("/topics/{topic_id}/review")
def review_topic(
    topic_id: str,
    request: GraphReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if request.review_status == "approved":
        raise_if_approval_blocked("topic", topic_approval_blockers(topic))
    result = apply_graph_review(session, topic, "topic", topic_id, request, actor)
    return {"topic": serialize_topic_for_admin(session, topic), "review_event": result}


@router.patch("/topics/{topic_id}/correction")
def save_topic_correction(
    topic_id: str,
    request: TopicCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    updates = request.model_dump(exclude_unset=True)
    notes = updates.pop("reviewer_notes", None)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one topic correction field is required")
    if "name" in updates:
        normalized = normalize_topic(str(updates["name"] or ""))
        if normalized is None:
            raise HTTPException(status_code=422, detail="name must normalize to a valid topic")
        normalized_name, display_name = normalized
        collision = session.exec(
            select(Topic).where(Topic.normalized_name == normalized_name).where(Topic.topic_id != topic_id)
        ).first()
        if collision is not None:
            raise HTTPException(status_code=409, detail="Topic name already belongs to another topic")
        updates["name"] = display_name
        updates["normalized_name"] = normalized_name
    previous_status = topic.review_status
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        update_if_changed(topic, field_name, new_value, diff)
    if not diff:
        return {"topic": serialize_topic_for_admin(session, topic), "review_event": None}
    update_if_changed(topic, "review_status", "needs_review", diff)
    apply_review_metadata(topic, "needs_review", notes, actor)
    topic.updated_at = utc_now()
    dependent_resets = reset_topic_link_reviews(session, topic_id)
    diff["dependent_link_reviews_reset"] = {"before": None, "after": dependent_resets}
    event = create_review_event(
        session,
        item_type="topic",
        item_id=topic_id,
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=notes,
        diff=diff,
        actor=actor,
    )
    session.add(topic)
    session.add(event)
    session.commit()
    session.refresh(topic)
    return {"topic": serialize_topic_for_admin(session, topic), "review_event": serialize_review_event(event)}


@router.patch("/paper-topics/{link_id}/review")
def review_paper_topic(
    link_id: str,
    request: GraphReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    link = session.get(PaperTopic, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Paper-topic link not found")
    if request.review_status == "approved":
        raise_if_approval_blocked("paper_topic", paper_topic_approval_blockers(session, link))
    result = apply_graph_review(session, link, "paper_topic", link_id, request, actor)
    return {"paper_topic": serialize_paper_topic_for_admin(session, link), "review_event": result}


@router.patch("/paper-topics/{link_id}/correction")
def save_paper_topic_correction(
    link_id: str,
    request: PaperTopicCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    link = session.get(PaperTopic, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Paper-topic link not found")
    result = apply_graph_correction(session, link, "paper_topic", link_id, request, actor)
    return {"paper_topic": serialize_paper_topic_for_admin(session, link), "review_event": result}


@router.patch("/author-topics/{link_id}/review")
def review_author_topic(
    link_id: str,
    request: GraphReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    link = session.get(AuthorTopic, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Author-topic link not found")
    if request.review_status == "approved":
        raise_if_approval_blocked("author_topic", author_topic_approval_blockers(session, link))
    result = apply_graph_review(session, link, "author_topic", link_id, request, actor)
    return {"author_topic": serialize_author_topic_for_admin(session, link), "review_event": result}


@router.patch("/author-topics/{link_id}/correction")
def save_author_topic_correction(
    link_id: str,
    request: AuthorTopicCorrectionRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, Any]:
    link = session.get(AuthorTopic, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Author-topic link not found")
    result = apply_graph_correction(session, link, "author_topic", link_id, request, actor)
    return {"author_topic": serialize_author_topic_for_admin(session, link), "review_event": result}


@router.get("/review-events")
def review_events(
    session: Annotated[Session, Depends(get_session)],
    item_type: Optional[str] = Query(default=None, max_length=100),
    item_id: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    statement = select(ReviewEvent)
    count_statement = select(func.count()).select_from(ReviewEvent)
    if item_type:
        statement = statement.where(ReviewEvent.item_type == item_type)
        count_statement = count_statement.where(ReviewEvent.item_type == item_type)
    if item_id:
        statement = statement.where(ReviewEvent.item_id == item_id)
        count_statement = count_statement.where(ReviewEvent.item_id == item_id)
    total = int(session.exec(count_statement).one())
    events = session.exec(
        statement.order_by(desc(ReviewEvent.created_at), desc(ReviewEvent.review_event_id))
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [serialize_review_event(event) for event in events],
    }


def utc_now() -> datetime:
    return datetime.now(UTC)


def raise_if_approval_blocked(item_type: str, blockers: list[str]) -> None:
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "approval_blocked",
                "item_type": item_type,
                "approval_blockers": blockers,
            },
        )


def apply_graph_review(
    session: Session,
    record: Any,
    item_type: str,
    item_id: str,
    request: GraphReviewRequest,
    actor: AuthenticatedActor,
) -> dict[str, Any]:
    previous_status = record.review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(record, "review_status", request.review_status, diff)
    update_if_changed(record, "reviewer_notes", request.reviewer_notes, diff)
    apply_review_metadata(record, request.review_status, request.reviewer_notes, actor)
    if hasattr(record, "updated_at"):
        record.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type=item_type,
        item_id=item_id,
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
        actor=actor,
    )
    session.add(record)
    session.add(event)
    session.commit()
    session.refresh(record)
    return serialize_review_event(event)


def apply_graph_correction(
    session: Session,
    record: Any,
    item_type: str,
    item_id: str,
    request: BaseModel,
    actor: AuthenticatedActor,
) -> dict[str, Any] | None:
    updates = request.model_dump(exclude_unset=True)
    notes = updates.pop("reviewer_notes", None)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one correction field is required")
    previous_status = record.review_status
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        update_if_changed(record, field_name, new_value, diff)
    if not diff:
        return None
    update_if_changed(record, "review_status", "needs_review", diff)
    apply_review_metadata(record, "needs_review", notes, actor)
    if hasattr(record, "updated_at"):
        record.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type=item_type,
        item_id=item_id,
        action="correction_saved",
        previous_status=previous_status,
        new_status="needs_review",
        notes=notes,
        diff=diff,
        actor=actor,
    )
    session.add(record)
    session.add(event)
    session.commit()
    session.refresh(record)
    return serialize_review_event(event)


def reset_topic_link_reviews(session: Session, topic_id: str) -> dict[str, list[str]]:
    reset: dict[str, list[str]] = {"paper_topic_ids": [], "author_topic_ids": []}
    now = utc_now()
    for item_type, model, key in (
        ("paper_topic_ids", PaperTopic, PaperTopic.topic_id),
        ("author_topic_ids", AuthorTopic, AuthorTopic.topic_id),
    ):
        for link in session.exec(select(model).where(key == topic_id)).all():
            if link.review_status != "needs_review":
                reset[item_type].append(link.link_id)
            link.review_status = "needs_review"
            link.reviewer_notes = "Upstream topic correction requires re-review."
            link.reviewed_at = None
            link.reviewed_by = None
            link.updated_at = now
            session.add(link)
    return reset


def reset_author_topic_reviews(
    session: Session,
    author_ids: set[int],
    *,
    reason: str,
) -> list[str]:
    reset_ids: list[str] = []
    now = utc_now()
    for link in session.exec(select(AuthorTopic).where(AuthorTopic.author_id.in_(author_ids))).all():
        if link.review_status != "needs_review":
            reset_ids.append(link.link_id)
        link.review_status = "needs_review"
        link.reviewer_notes = reason
        link.reviewed_at = None
        link.reviewed_by = None
        link.updated_at = now
        session.add(link)
    return reset_ids


def update_if_changed(record: Any, field_name: str, new_value: Any, diff: dict[str, dict[str, Any]]) -> None:
    old_value = getattr(record, field_name)
    if old_value != new_value:
        diff[field_name] = {"before": old_value, "after": new_value}
        setattr(record, field_name, new_value)


def apply_review_metadata(
    record: Any,
    review_status: str,
    reviewer_notes: Optional[str],
    actor: AuthenticatedActor,
) -> None:
    record.review_status = review_status
    record.reviewer_notes = reviewer_notes
    record.reviewed_at = utc_now()
    record.reviewed_by = actor.actor_id


def create_review_event(
    session: Session,
    *,
    item_type: str,
    item_id: str,
    action: str,
    previous_status: Optional[str],
    new_status: Optional[str],
    notes: Optional[str],
    diff: dict[str, Any],
    actor: AuthenticatedActor,
) -> ReviewEvent:
    latest_event = session.exec(
        select(ReviewEvent).order_by(desc(ReviewEvent.created_at), desc(ReviewEvent.review_event_id)).limit(1)
    ).first()
    created_at = utc_now()
    review_event_id = str(uuid.uuid4())
    previous_event_hash = latest_event.event_hash if latest_event else None
    event_hash = ReviewEvent.calculate_hash(
        review_event_id=review_event_id,
        previous_event_hash=previous_event_hash,
        item_type=item_type,
        item_id=item_id,
        action=action,
        previous_status=previous_status,
        new_status=new_status,
        reviewer_id=actor.actor_id,
        reviewer_name=actor.display_name,
        reviewer_type=actor.reviewer_type,
        reviewer_role=actor.role,
        request_id=actor.request_id,
        reviewer_notes=notes,
        diff_json=diff,
        created_at=created_at,
    )
    return ReviewEvent(
        review_event_id=review_event_id,
        item_type=item_type,
        item_id=item_id,
        action=action,
        previous_status=previous_status,
        new_status=new_status,
        reviewer_name=actor.display_name,
        reviewer_id=actor.actor_id,
        reviewer_type=actor.reviewer_type,
        reviewer_role=actor.role,
        request_id=actor.request_id,
        reviewer_notes=notes,
        diff_json=diff,
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
        created_at=created_at,
    )


def enforce_review_transition(
    previous_status: str,
    new_status: str,
    actor: AuthenticatedActor,
) -> None:
    reviewer_targets = {"needs_review", "needs_reprocess"}
    reviewer_targets.add("ai_reviewed" if actor.reviewer_type == "ai" else "reviewed")
    if actor.role == "reviewer" and new_status not in reviewer_targets:
        raise HTTPException(
            status_code=403,
            detail="Reviewers may record review/reprocess state; approval and rejection require an admin",
        )
    if actor.reviewer_type != "human" and new_status in {"reviewed", "approved", "rejected"}:
        raise HTTPException(
            status_code=403,
            detail="Only a human admin/reviewer may record human review, approval, or rejection",
        )
    if actor.reviewer_type != "ai" and new_status == "ai_reviewed":
        raise HTTPException(status_code=403, detail="Only an AI reviewer actor may record ai_reviewed")
    if previous_status == new_status:
        return
    allowed = {
        "needs_review": {"ai_reviewed", "reviewed", "needs_reprocess", "rejected", "approved"},
        "ai_reviewed": {"needs_review", "needs_reprocess", "approved", "rejected"},
        "reviewed": {"needs_review", "needs_reprocess", "approved", "rejected"},
        "approved": {"needs_review", "needs_reprocess"},
        "rejected": {"needs_review", "needs_reprocess"},
        "needs_reprocess": {"needs_review", "ai_reviewed", "reviewed", "rejected"},
    }
    if new_status not in allowed.get(previous_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Unsupported review transition: {previous_status} -> {new_status}",
        )


def transition_allowed(previous_status: str, new_status: str, actor: AuthenticatedActor) -> bool:
    try:
        enforce_review_transition(previous_status, new_status, actor)
    except HTTPException:
        return False
    return True


def action_for_status(status: str, *, corrected: bool) -> str:
    if corrected:
        return "corrected"
    return {
        "approved": "approved",
        "rejected": "rejected",
        "reviewed": "reviewed",
        "ai_reviewed": "ai_reviewed",
        "needs_reprocess": "marked_needs_reprocess",
        "needs_review": "marked_needs_review",
    }.get(status, "reviewed")


def author_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(Author)
    if review_status:
        statement = statement.where(Author.identity_review_status == review_status)
    authors = session.exec(statement).all()
    return [
        {
            "item_type": "author",
            "item_id": str(author.id),
            "title": author.canonical_name or author.name,
            "label": author.canonical_name or author.name,
            "status": author.identity_review_status,
            "grounding_status": None,
            "warnings": (
                ["Identity is unresolved or ambiguous and cannot be approved without correction."]
                if author.identity_status in {"unresolved", "ambiguous"}
                else []
            ),
            "created_at": format_dt(author.created_at),
            "updated_at": format_dt(author.updated_at),
            "frontend_link": f"author:{author.id}",
            "approval_blockers": author_approval_blockers(session, author),
            "details": serialize_author_for_admin(session, author),
        }
        for author in authors
        if author.id is not None
    ]


def author_alias_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(AuthorAlias)
    if review_status:
        statement = statement.where(AuthorAlias.review_status == review_status)
    aliases = session.exec(statement).all()
    return [
        {
            "item_type": "author_alias",
            "item_id": alias.alias_id,
            "title": alias.alias,
            "label": alias.alias,
            "status": alias.review_status,
            "grounding_status": None,
            "warnings": [],
            "created_at": format_dt(alias.created_at),
            "updated_at": format_dt(alias.updated_at),
            "frontend_link": f"author:{alias.canonical_author_id}",
            "approval_blockers": author_alias_approval_blockers(session, alias),
            "details": serialize_author_alias_for_admin(session, alias),
        }
        for alias in aliases
    ]


def topic_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(Topic)
    if review_status:
        statement = statement.where(Topic.review_status == review_status)
    topics = session.exec(statement).all()
    return [
        {
            "item_type": "topic",
            "item_id": topic.topic_id,
            "title": topic.name,
            "label": topic.name,
            "status": topic.review_status,
            "grounding_status": None,
            "warnings": [],
            "created_at": format_dt(topic.created_at),
            "updated_at": format_dt(topic.updated_at),
            "frontend_link": f"topic:{topic.topic_id}",
            "approval_blockers": topic_approval_blockers(topic),
            "details": serialize_topic_for_admin(session, topic),
        }
        for topic in topics
    ]


def paper_topic_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(PaperTopic)
    if review_status:
        statement = statement.where(PaperTopic.review_status == review_status)
    links = session.exec(statement).all()
    paper_titles = {
        paper.paper_id: paper.title
        for paper in session.exec(select(Paper).where(Paper.paper_id.in_([link.paper_id for link in links]))).all()
    } if links else {}
    topic_names = {
        topic.topic_id: topic.name
        for topic in session.exec(select(Topic).where(Topic.topic_id.in_([link.topic_id for link in links]))).all()
    } if links else {}
    return [
        {
            "item_type": "paper_topic",
            "item_id": link.link_id,
            "title": f"{paper_titles.get(link.paper_id, link.paper_id)} -> {topic_names.get(link.topic_id, link.topic_id)}",
            "label": topic_names.get(link.topic_id, link.topic_id),
            "status": link.review_status,
            "grounding_status": None,
            "warnings": [],
            "created_at": format_dt(link.created_at),
            "updated_at": format_dt(link.updated_at),
            "frontend_link": f"paper:{link.paper_id}",
            "approval_blockers": paper_topic_approval_blockers(session, link),
            "details": serialize_paper_topic_for_admin(session, link),
        }
        for link in links
    ]


def author_topic_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(AuthorTopic)
    if review_status:
        statement = statement.where(AuthorTopic.review_status == review_status)
    links = session.exec(statement).all()
    authors = {
        author.id: author.canonical_name or author.name
        for author in session.exec(select(Author).where(Author.id.in_([link.author_id for link in links]))).all()
    } if links else {}
    topic_names = {
        topic.topic_id: topic.name
        for topic in session.exec(select(Topic).where(Topic.topic_id.in_([link.topic_id for link in links]))).all()
    } if links else {}
    return [
        {
            "item_type": "author_topic",
            "item_id": link.link_id,
            "title": f"{authors.get(link.author_id, str(link.author_id))} -> {topic_names.get(link.topic_id, link.topic_id)}",
            "label": topic_names.get(link.topic_id, link.topic_id),
            "status": link.review_status,
            "grounding_status": None,
            "warnings": [],
            "created_at": format_dt(link.created_at),
            "updated_at": format_dt(link.updated_at),
            "frontend_link": f"author:{link.author_id}",
            "approval_blockers": author_topic_approval_blockers(session, link),
            "details": serialize_author_topic_for_admin(session, link),
        }
        for link in links
    ]


def paper_queue_items(session: Session, review_status: Optional[str]) -> list[dict[str, Any]]:
    statement = select(Paper)
    if review_status:
        statement = statement.where(Paper.review_status == review_status)
    papers = session.exec(statement).all()
    return [
        {
            "item_type": "paper",
            "item_id": paper.paper_id,
            "title": paper.title,
            "label": paper.title,
            "status": paper.review_status,
            "grounding_status": None,
            "warnings": paper_warnings(paper),
            "created_at": format_dt(paper.created_at),
            "updated_at": format_dt(paper.updated_at),
            "frontend_link": f"paper:{paper.paper_id}",
            "details": serialize_paper_for_admin(session, paper),
        }
        for paper in papers
    ]


def answer_queue_items(
    session: Session,
    review_status: Optional[str],
    grounding_status: Optional[str],
) -> list[dict[str, Any]]:
    statement = select(RAGAnswer)
    if review_status:
        statement = statement.where(RAGAnswer.review_status == review_status)
    if grounding_status:
        statement = statement.where(RAGAnswer.grounding_status == grounding_status)
    answers = session.exec(statement).all()
    return [
        {
            "item_type": "rag_answer",
            "item_id": answer.answer_id,
            "title": answer.question,
            "label": answer.question,
            "status": answer.review_status,
            "grounding_status": answer.grounding_status,
            "warnings": answer.warnings_json,
            "created_at": format_dt(answer.created_at),
            "updated_at": None,
            "frontend_link": "admin:answers",
            "details": serialize_answer_for_admin(answer),
        }
        for answer in answers
    ]


def recommendation_queue_items(
    session: Session,
    review_status: Optional[str],
    grounding_status: Optional[str],
) -> list[dict[str, Any]]:
    statement = select(ThesisRecommendation)
    if review_status:
        statement = statement.where(ThesisRecommendation.review_status == review_status)
    if grounding_status:
        statement = statement.where(ThesisRecommendation.grounding_status == grounding_status)
    recommendations = session.exec(statement).all()
    return [
        {
            "item_type": "thesis_recommendation",
            "item_id": recommendation.recommendation_id,
            "title": recommendation_label(recommendation),
            "label": recommendation_label(recommendation),
            "status": recommendation.review_status,
            "grounding_status": recommendation.grounding_status,
            "warnings": recommendation.warnings_json,
            "created_at": format_dt(recommendation.created_at),
            "updated_at": None,
            "frontend_link": "admin:recommendations",
            "details": serialize_recommendation_for_admin(recommendation),
        }
        for recommendation in recommendations
    ]


def artifact_queue_items(
    session: Session,
    review_status: Optional[str],
    grounding_status: Optional[str],
) -> list[dict[str, Any]]:
    statement = select(PaperArtifact)
    if review_status:
        statement = statement.where(PaperArtifact.review_status == review_status)
    if grounding_status:
        statement = statement.where(PaperArtifact.grounding_status == grounding_status)
    artifacts = session.exec(statement).all()
    paper_titles = {
        paper.paper_id: paper.title
        for paper in session.exec(select(Paper).where(Paper.paper_id.in_([artifact.paper_id for artifact in artifacts]))).all()
    } if artifacts else {}
    return [
        {
            "item_type": "paper_artifact",
            "item_id": artifact.artifact_id,
            "title": f"{artifact.artifact_type.replace('_', ' ')}: {paper_titles.get(artifact.paper_id, artifact.paper_id)}",
            "label": artifact.artifact_type.replace("_", " "),
            "status": artifact.review_status,
            "grounding_status": artifact.grounding_status,
            "warnings": artifact.warnings_json,
            "created_at": format_dt(artifact.created_at),
            "updated_at": format_dt(artifact.updated_at),
            "frontend_link": f"paper:{artifact.paper_id}",
            "details": serialize_artifact_for_admin(artifact),
        }
        for artifact in artifacts
    ]


def author_dependency(author: Author | None) -> dict[str, Any]:
    return {
        "author_id": author.id if author else None,
        "exists": author is not None,
        "review_status": author.review_status if author else None,
        "identity_review_status": author.identity_review_status if author else None,
        "identity_status": author.identity_status if author else None,
    }


def topic_dependency(topic: Topic | None, topic_id: str) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id if topic else topic_id,
        "exists": topic is not None,
        "review_status": topic.review_status if topic else None,
    }


def paper_dependency(paper: Paper | None, paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id if paper else paper_id,
        "exists": paper is not None,
        "review_status": paper.review_status if paper else None,
    }


def author_approval_blockers(session: Session, author: Author) -> list[str]:
    if author.identity_status in {"unresolved", "ambiguous"}:
        return ["identity_unresolved_or_ambiguous"]
    if author.identity_status == "resolved" and (not author.canonical_name or not author.normalized_name):
        return ["canonical_metadata_missing"]
    if author.identity_status == "merged":
        target = session.get(Author, author.merged_into_author_id) if author.merged_into_author_id else None
        if (
            target is None
            or target.identity_status != "resolved"
            or target.review_status != "approved"
            or target.identity_review_status != "approved"
        ):
            return ["merge_target_not_approved"]
    if author.identity_status not in {"resolved", "merged", "invalid"}:
        return ["identity_unresolved_or_ambiguous"]
    return []


def author_alias_approval_blockers(session: Session, alias: AuthorAlias) -> list[str]:
    author = session.get(Author, alias.canonical_author_id)
    if author is None:
        return ["author_missing"]
    blockers: list[str] = []
    if author.review_status != "approved":
        blockers.append("author_not_approved")
    if author.identity_review_status != "approved":
        blockers.append("author_identity_not_approved")
    if author.identity_status != "resolved":
        blockers.append("author_not_resolved")
    return blockers


def topic_approval_blockers(topic: Topic) -> list[str]:
    return [] if topic.name and topic.normalized_name else ["topic_metadata_missing"]


def paper_topic_approval_blockers(session: Session, link: PaperTopic) -> list[str]:
    paper = session.get(Paper, link.paper_id)
    topic = session.get(Topic, link.topic_id)
    blockers: list[str] = []
    if paper is None:
        blockers.append("paper_missing")
    elif paper.review_status != "approved":
        blockers.append("paper_metadata_not_approved")
    if topic is None:
        blockers.append("topic_missing")
    elif topic.review_status != "approved":
        blockers.append("topic_not_approved")
    return blockers


def author_topic_approval_blockers(session: Session, link: AuthorTopic) -> list[str]:
    author = session.get(Author, link.author_id)
    topic = session.get(Topic, link.topic_id)
    blockers: list[str] = []
    if author is None:
        blockers.append("author_missing")
    else:
        if author.review_status != "approved":
            blockers.append("author_not_approved")
        if author.identity_review_status != "approved":
            blockers.append("author_identity_not_approved")
        if author.identity_status != "resolved":
            blockers.append("author_not_resolved")
    if topic is None:
        blockers.append("topic_missing")
    elif topic.review_status != "approved":
        blockers.append("topic_not_approved")
    return blockers


def serialize_author_for_admin(session: Session, author: Author) -> dict[str, Any]:
    merge_target = session.get(Author, author.merged_into_author_id) if author.merged_into_author_id else None
    return {
        "author_id": author.id,
        "name": author.name,
        "canonical_name": author.canonical_name,
        "normalized_name": author.normalized_name,
        "affiliation": author.affiliation,
        "email": author.email,
        "profile_url": author.profile_url,
        "research_topics": author.research_topics,
        "paper_count": author.paper_count,
        "review_status": author.review_status,
        "identity_status": author.identity_status,
        "identity_review_status": author.identity_review_status,
        "identity_review_notes": author.identity_review_notes,
        "identity_reviewed_at": format_dt(author.identity_reviewed_at),
        "identity_reviewed_by": author.identity_reviewed_by,
        "merged_into_author_id": author.merged_into_author_id,
        "persistent_identifier": author.persistent_identifier,
        "persistent_identifier_source": author.persistent_identifier_source,
        "approval_blockers": author_approval_blockers(session, author),
        "dependencies": {"merge_target": author_dependency(merge_target)} if author.identity_status == "merged" else {},
        "created_at": format_dt(author.created_at),
        "updated_at": format_dt(author.updated_at),
    }


def serialize_author_alias_for_admin(session: Session, alias: AuthorAlias) -> dict[str, Any]:
    author = session.get(Author, alias.canonical_author_id)
    return {
        "alias_id": alias.alias_id,
        "canonical_author_id": alias.canonical_author_id,
        "alias": alias.alias,
        "normalized_alias": alias.normalized_alias,
        "source": alias.source,
        "review_status": alias.review_status,
        "reviewer_notes": alias.reviewer_notes,
        "reviewed_at": format_dt(alias.reviewed_at),
        "reviewed_by": alias.reviewed_by,
        "approval_blockers": author_alias_approval_blockers(session, alias),
        "dependencies": {"author": author_dependency(author)},
        "created_at": format_dt(alias.created_at),
        "updated_at": format_dt(alias.updated_at),
    }


def serialize_topic_for_admin(_session: Session, topic: Topic) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id,
        "name": topic.name,
        "normalized_name": topic.normalized_name,
        "description": topic.description,
        "source": topic.source,
        "review_status": topic.review_status,
        "reviewer_notes": topic.reviewer_notes,
        "reviewed_at": format_dt(topic.reviewed_at),
        "reviewed_by": topic.reviewed_by,
        "approval_blockers": topic_approval_blockers(topic),
        "dependencies": {},
        "created_at": format_dt(topic.created_at),
        "updated_at": format_dt(topic.updated_at),
    }


def serialize_paper_topic_for_admin(session: Session, link: PaperTopic) -> dict[str, Any]:
    paper = session.get(Paper, link.paper_id)
    topic = session.get(Topic, link.topic_id)
    return {
        "link_id": link.link_id,
        "paper_id": link.paper_id,
        "topic_id": link.topic_id,
        "score": link.score,
        "evidence_json": link.evidence_json,
        "source": link.source,
        "review_status": link.review_status,
        "reviewer_notes": link.reviewer_notes,
        "reviewed_at": format_dt(link.reviewed_at),
        "reviewed_by": link.reviewed_by,
        "approval_blockers": paper_topic_approval_blockers(session, link),
        "dependencies": {
            "paper": paper_dependency(paper, link.paper_id),
            "topic": topic_dependency(topic, link.topic_id),
        },
        "created_at": format_dt(link.created_at),
        "updated_at": format_dt(link.updated_at),
    }


def serialize_author_topic_for_admin(session: Session, link: AuthorTopic) -> dict[str, Any]:
    author = session.get(Author, link.author_id)
    topic = session.get(Topic, link.topic_id)
    return {
        "link_id": link.link_id,
        "author_id": link.author_id,
        "topic_id": link.topic_id,
        "paper_count": link.paper_count,
        "score": link.score,
        "evidence_json": link.evidence_json,
        "review_status": link.review_status,
        "reviewer_notes": link.reviewer_notes,
        "reviewed_at": format_dt(link.reviewed_at),
        "reviewed_by": link.reviewed_by,
        "approval_blockers": author_topic_approval_blockers(session, link),
        "dependencies": {
            "author": author_dependency(author),
            "topic": topic_dependency(topic, link.topic_id),
        },
        "created_at": format_dt(link.created_at),
        "updated_at": format_dt(link.updated_at),
    }


def serialize_paper_for_admin(session: Session, paper: Paper) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "publication_date_raw": paper.publication_date_raw,
        "venue": paper.venue,
        "topics": paper.topics,
        "source_url": paper.source_url,
        "pdf_url": paper.pdf_url,
        "abstract": paper.abstract,
        "doi": paper.doi,
        "keywords": paper.keywords,
        "metadata_provenance": paper.metadata_provenance,
        "metadata_field_reviews": paper.metadata_field_reviews,
        "pdf_text_status": paper.pdf_text_status,
        "extraction_generation_id": paper.extraction_generation_id,
        "extraction_input_pdf_sha256": paper.extraction_input_pdf_sha256,
        "extraction_config_sha256": paper.extraction_config_sha256,
        "chunk_extraction_generation_id": paper.chunk_extraction_generation_id,
        "chunk_generation_id": paper.chunk_generation_id,
        "public_index_generation_id": paper.public_index_generation_id,
        "pdf_unavailability_reason": paper.pdf_unavailability_reason,
        "pdf_unavailability_detail": paper.pdf_unavailability_detail,
        "possible_scanned_pdf": paper.possible_scanned_pdf,
        "extraction_content_type": paper.extraction_content_type,
        "ocr_status": paper.ocr_status,
        "ocr_provider": paper.ocr_provider,
        "ocr_provider_version": paper.ocr_provider_version,
        "ocr_pages_count": paper.ocr_pages_count,
        "ocr_review_required": paper.ocr_review_required,
        "pdf_title_match_status": paper.pdf_title_match_status,
        "pdf_title_match_score": paper.pdf_title_match_score,
        "corpus_eligibility_status": paper.corpus_eligibility_status,
        "corpus_exclusion_reason": paper.corpus_exclusion_reason,
        **publication_state(session, paper),
        "review_status": paper.review_status,
        "reviewer_notes": paper.reviewer_notes,
        "reviewed_at": format_dt(paper.reviewed_at),
        "reviewed_by": paper.reviewed_by,
        "extraction_review_status": paper.extraction_review_status,
        "extraction_reviewer_notes": paper.extraction_reviewer_notes,
        "extraction_reviewed_at": format_dt(paper.extraction_reviewed_at),
        "extraction_reviewed_by": paper.extraction_reviewed_by,
        "created_at": format_dt(paper.created_at),
        "updated_at": format_dt(paper.updated_at),
    }


def serialize_answer_for_admin(answer: RAGAnswer) -> dict[str, Any]:
    return {
        "answer_id": answer.answer_id,
        "question": answer.question,
        "answer": answer.answer,
        "citations": answer.citations_json,
        "grounding_status": answer.grounding_status,
        "warnings": answer.warnings_json,
        "unsupported_claims": answer.unsupported_claims_json,
        "review_status": answer.review_status,
        "reviewer_notes": answer.reviewer_notes,
        "reviewed_at": format_dt(answer.reviewed_at),
        "reviewed_by": answer.reviewed_by,
        "citation_correct": answer.citation_correct,
        "answer_faithfulness_score": answer.answer_faithfulness_score,
        "usefulness_score": answer.usefulness_score,
        "created_at": format_dt(answer.created_at),
    }


def serialize_recommendation_for_admin(recommendation: ThesisRecommendation) -> dict[str, Any]:
    correction_blockers = recommendation_correction_blockers(recommendation)
    correction_used = bool(recommendation.corrected_recommendations_json)
    approved = recommendation.review_status == "approved" and not correction_blockers
    return {
        "recommendation_id": recommendation.recommendation_id,
        "request": recommendation.request_json,
        "recommendations": recommendation.recommendations_json,
        "grounding_status": recommendation.grounding_status,
        "warnings": recommendation.warnings_json,
        "review_status": recommendation.review_status,
        "reviewer_notes": recommendation.reviewer_notes,
        "reviewed_at": format_dt(recommendation.reviewed_at),
        "reviewed_by": recommendation.reviewed_by,
        "corrected_recommendations_json": recommendation.corrected_recommendations_json,
        "correction_grounding_status": recommendation.correction_grounding_status,
        "correction_source_chunk_ids": recommendation.correction_source_chunk_ids_json,
        "correction_citations": recommendation.correction_citations_json,
        "correction_runtime_provenance": recommendation.correction_runtime_provenance_json,
        "approval_blockers": correction_blockers,
        "effective_recommendations_json": (
            recommendation.corrected_recommendations_json
            if approved and correction_used
            else {"items": recommendation.recommendations_json} if approved else None
        ),
        "effective_provenance": {
            "available": approved,
            "source": "reviewer_correction" if approved and correction_used else "generated" if approved else None,
            "grounding_status": (
                recommendation.correction_grounding_status
                if approved and correction_used
                else recommendation.grounding_status if approved else None
            ),
            "source_chunk_ids": (
                recommendation.correction_source_chunk_ids_json if approved and correction_used else None
            ),
            "citations": recommendation.correction_citations_json if approved and correction_used else None,
            "original_generated_evidence_inherited": False if approved and correction_used else None,
            "correction_runtime": (
                recommendation.correction_runtime_provenance_json if approved and correction_used else None
            ),
            "approved_version": format_dt(recommendation.reviewed_at) if approved else None,
            "reviewed_by": recommendation.reviewed_by if approved else None,
        },
        "created_at": format_dt(recommendation.created_at),
    }


def serialize_artifact_for_admin(artifact: PaperArtifact) -> dict[str, Any]:
    correction_blockers = artifact_correction_blockers(artifact)
    approved = artifact.review_status == "approved" and not correction_blockers
    correction_used = bool(artifact.corrected_json) or artifact.corrected_text is not None
    return {
        "artifact_id": artifact.artifact_id,
        "paper_id": artifact.paper_id,
        "artifact_type": artifact.artifact_type,
        "generated_text": artifact.generated_text,
        "generated_json": artifact.generated_json,
        "citations": artifact.citations_json,
        "grounding_status": artifact.grounding_status,
        "generation_status": artifact.generation_status,
        "warnings": artifact.warnings_json,
        "review_status": artifact.review_status,
        "reviewer_notes": artifact.reviewer_notes,
        "reviewed_at": format_dt(artifact.reviewed_at),
        "reviewed_by": artifact.reviewed_by,
        "corrected_text": artifact.corrected_text,
        "corrected_json": artifact.corrected_json,
        "correction_grounding_status": artifact.correction_grounding_status,
        "correction_source_chunk_ids": artifact.correction_source_chunk_ids_json,
        "correction_citations": artifact.correction_citations_json,
        "correction_runtime_provenance": artifact.correction_runtime_provenance_json,
        "approval_blockers": correction_blockers,
        "effective_json": (
            artifact.corrected_json if approved and artifact.corrected_json else artifact.generated_json if approved else None
        ),
        "effective_text": (
            artifact.corrected_text
            if approved and artifact.corrected_text is not None
            else artifact.generated_text if approved else None
        ),
        "effective_provenance": {
            "available": approved,
            "source": "reviewer_correction" if approved and correction_used else "generated" if approved else None,
            "grounding_status": (
                artifact.correction_grounding_status
                if approved and correction_used
                else artifact.grounding_status if approved else None
            ),
            "source_chunk_ids": artifact.correction_source_chunk_ids_json if approved and correction_used else None,
            "citations": artifact.correction_citations_json if approved and correction_used else None,
            "original_generated_evidence_inherited": False if approved and correction_used else None,
            "correction_runtime": artifact.correction_runtime_provenance_json if approved and correction_used else None,
            "approved_version": format_dt(artifact.reviewed_at) if approved else None,
            "reviewed_by": artifact.reviewed_by if approved else None,
        },
        "created_at": format_dt(artifact.created_at),
        "updated_at": format_dt(artifact.updated_at),
    }


def serialize_review_event(event: ReviewEvent) -> dict[str, Any]:
    return {
        "review_event_id": event.review_event_id,
        "item_type": event.item_type,
        "item_id": event.item_id,
        "action": event.action,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "reviewer_name": event.reviewer_name,
        "reviewer_id": event.reviewer_id,
        "reviewer_type": event.reviewer_type,
        "reviewer_role": event.reviewer_role,
        "request_id": event.request_id,
        "reviewer_notes": event.reviewer_notes,
        "diff": event.diff_json,
        "previous_event_hash": event.previous_event_hash,
        "event_hash": event.event_hash,
        "created_at": format_dt(event.created_at),
    }


def verify_review_event_chain(events: list[ReviewEvent]) -> dict[str, Any]:
    previous_hash: Optional[str] = None
    invalid_event_ids: list[str] = []
    legacy_unverified = 0
    verified = 0
    for event in events:
        if not event.event_hash:
            legacy_unverified += 1
            previous_hash = None
            continue
        expected = ReviewEvent.calculate_hash(
            review_event_id=event.review_event_id,
            previous_event_hash=event.previous_event_hash,
            item_type=event.item_type,
            item_id=event.item_id,
            action=event.action,
            previous_status=event.previous_status,
            new_status=event.new_status,
            reviewer_id=event.reviewer_id,
            reviewer_name=event.reviewer_name,
            reviewer_type=event.reviewer_type,
            reviewer_role=event.reviewer_role,
            request_id=event.request_id,
            reviewer_notes=event.reviewer_notes,
            diff_json=event.diff_json,
            created_at=event.created_at,
        )
        if event.previous_event_hash != previous_hash or event.event_hash != expected:
            invalid_event_ids.append(event.review_event_id)
        else:
            verified += 1
        previous_hash = event.event_hash
    return {
        "status": "invalid" if invalid_event_ids else "legacy_unverified" if legacy_unverified else "verified",
        "verified_events": verified,
        "legacy_unverified_events": legacy_unverified,
        "invalid_event_ids": invalid_event_ids,
    }


def paper_warnings(paper: Paper) -> list[str]:
    warnings: list[str] = []
    if paper.pdf_text_status == "missing_pdf":
        warnings.append("Missing direct PDF.")
    if paper.pdf_text_status in {
        "extraction_failed",
        "download_failed",
        "invalid_pdf",
        "no_text",
        "scanned_pdf",
        "blank_pdf",
    }:
        warnings.append(f"Extraction status is {paper.pdf_text_status}.")
    if paper.possible_scanned_pdf:
        warnings.append("Possible scanned or image-heavy PDF.")
    if paper.ocr_review_required:
        warnings.append(f"OCR/extraction review required (OCR status: {paper.ocr_status}).")
    if not paper.authors:
        warnings.append("Authors need review.")
    if not paper.venue:
        warnings.append("Venue needs review.")
    return warnings


def recommendation_label(recommendation: ThesisRecommendation) -> str:
    interests = recommendation.request_json.get("interests") if isinstance(recommendation.request_json, dict) else None
    if interests:
        return f"Thesis recommendations for {interests}"
    return f"Thesis recommendation run {recommendation.recommendation_id[:8]}"


def status_breakdown(records: list[Any]) -> dict[str, int]:
    counts = {
        "needs_review": 0,
        "ai_reviewed": 0,
        "reviewed": 0,
        "approved": 0,
        "rejected": 0,
        "needs_reprocess": 0,
    }
    for record in records:
        status = getattr(record, "review_status", "needs_review")
        counts[status] = counts.get(status, 0) + 1
    return counts


def grounding_breakdown(records: list[Any]) -> dict[str, int]:
    counts = {"grounded": 0, "partial": 0, "unsupported": 0}
    for record in records:
        status = getattr(record, "grounding_status", None)
        if status:
            counts[status] = counts.get(status, 0) + 1
    return counts


def count_by_attr(records: list[Any], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(getattr(record, attr, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def format_dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
