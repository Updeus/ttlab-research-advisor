from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, desc, func, select

from app.db import get_session
from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation
from app.security import AuthenticatedActor, require_reviewer

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_reviewer)],
)

ReviewStatus = Literal["needs_review", "ai_reviewed", "reviewed", "approved", "rejected", "needs_reprocess"]

REVIEWABLE_ITEM_TYPES = {
    "paper",
    "rag_answer",
    "thesis_recommendation",
    "paper_artifact",
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
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)
    corrected_text: Optional[str] = Field(default=None, max_length=250_000)
    corrected_json: Optional[dict[str, Any]] = None


class RecommendationReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)
    corrected_recommendations_json: Optional[dict[str, Any] | list[dict[str, Any]]] = None


class AnswerReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)
    citation_correct: Optional[bool] = None
    answer_faithfulness_score: Optional[int] = Field(default=None, ge=1, le=5)
    usefulness_score: Optional[int] = Field(default=None, ge=1, le=5)


class ExtractionReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = Field(default=None, max_length=4_000)


@router.get("/overview")
def admin_overview(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
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
    correction_changed = (
        (request.corrected_text is not None and request.corrected_text != artifact.corrected_text)
        or (request.corrected_json is not None and request.corrected_json != artifact.corrected_json)
    )
    target_status = "needs_review" if correction_changed else request.review_status
    enforce_review_transition(previous_status, target_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(artifact, "review_status", target_status, diff)
    update_if_changed(artifact, "reviewer_notes", request.reviewer_notes, diff)
    if request.corrected_text is not None:
        update_if_changed(artifact, "corrected_text", request.corrected_text, diff)
    if request.corrected_json is not None:
        update_if_changed(artifact, "corrected_json", request.corrected_json, diff)
    apply_review_metadata(artifact, target_status, request.reviewer_notes, actor)
    artifact.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper_artifact",
        item_id=artifact.artifact_id,
        action=action_for_status(target_status, corrected=correction_changed),
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
    normalized_correction: dict[str, Any] | None = None
    if request.corrected_recommendations_json is not None:
        normalized_correction = (
            {"items": request.corrected_recommendations_json}
            if isinstance(request.corrected_recommendations_json, list)
            else request.corrected_recommendations_json
        )
    correction_changed = (
        normalized_correction is not None
        and normalized_correction != recommendation.corrected_recommendations_json
    )
    target_status = "needs_review" if correction_changed else request.review_status
    enforce_review_transition(previous_status, target_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(recommendation, "review_status", target_status, diff)
    update_if_changed(recommendation, "reviewer_notes", request.reviewer_notes, diff)
    if normalized_correction is not None:
        update_if_changed(
            recommendation,
            "corrected_recommendations_json",
            normalized_correction,
            diff,
        )
    apply_review_metadata(recommendation, target_status, request.reviewer_notes, actor)
    event = create_review_event(
        session,
        item_type="thesis_recommendation",
        item_id=recommendation.recommendation_id,
        action=action_for_status(target_status, corrected=correction_changed),
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
    previous_status = paper.review_status
    enforce_review_transition(previous_status, request.review_status, actor)
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(paper, "review_status", request.review_status, diff)
    update_if_changed(paper, "reviewer_notes", request.reviewer_notes, diff)
    apply_review_metadata(paper, request.review_status, request.reviewer_notes, actor)
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
    return {"paper": paper, "review_event": serialize_review_event(event)}


@router.get("/review-events")
def review_events(
    session: Annotated[Session, Depends(get_session)],
    item_type: Optional[str] = Query(default=None, max_length=100),
    item_id: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    statement = select(ReviewEvent)
    if item_type:
        statement = statement.where(ReviewEvent.item_type == item_type)
    if item_id:
        statement = statement.where(ReviewEvent.item_id == item_id)
    events = session.exec(statement.order_by(desc(ReviewEvent.created_at)).limit(limit)).all()
    return [serialize_review_event(event) for event in events]


def utc_now() -> datetime:
    return datetime.now(UTC)


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
            "details": serialize_paper_for_admin(paper),
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


def serialize_paper_for_admin(paper: Paper) -> dict[str, Any]:
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
        "review_status": paper.review_status,
        "reviewer_notes": paper.reviewer_notes,
        "reviewed_at": format_dt(paper.reviewed_at),
        "reviewed_by": paper.reviewed_by,
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
        "created_at": format_dt(recommendation.created_at),
    }


def serialize_artifact_for_admin(artifact: PaperArtifact) -> dict[str, Any]:
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
