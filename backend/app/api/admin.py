from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, desc, func, select

from app.db import get_session
from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation

router = APIRouter(prefix="/api/admin", tags=["admin"])

ReviewStatus = Literal["needs_review", "reviewed", "approved", "rejected", "needs_reprocess"]

REVIEWABLE_ITEM_TYPES = {
    "paper",
    "rag_answer",
    "thesis_recommendation",
    "paper_artifact",
}


class PaperPatchRequest(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    publication_date_raw: Optional[str] = None
    venue: Optional[str] = None
    topics: Optional[list[str]] = None
    source_url: Optional[str] = None
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    keywords: Optional[list[str]] = None
    review_status: Optional[ReviewStatus] = None
    reviewer_notes: Optional[str] = None


class ArtifactReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = None
    corrected_text: Optional[str] = None
    corrected_json: Optional[dict[str, Any]] = None


class RecommendationReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = None
    corrected_recommendations_json: Optional[dict[str, Any] | list[dict[str, Any]]] = None


class AnswerReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = None
    citation_correct: Optional[bool] = None
    answer_faithfulness_score: Optional[int] = Field(default=None, ge=1, le=5)
    usefulness_score: Optional[int] = Field(default=None, ge=1, le=5)


class ExtractionReviewRequest(BaseModel):
    review_status: ReviewStatus
    reviewer_notes: Optional[str] = None


@router.get("/overview")
def admin_overview(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    papers = list(session.exec(select(Paper)).all())
    answers = list(session.exec(select(RAGAnswer)).all())
    recommendations = list(session.exec(select(ThesisRecommendation)).all())
    artifacts = list(session.exec(select(PaperArtifact)).all())
    recent_events = list(
        session.exec(select(ReviewEvent).order_by(desc(ReviewEvent.created_at)).limit(10)).all()
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
        "recent_review_events": [serialize_review_event(event) for event in recent_events],
    }


@router.get("/review-queue")
def review_queue(
    session: Annotated[Session, Depends(get_session)],
    item_type: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default="needs_review"),
    grounding_status: Optional[str] = Query(default=None),
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
) -> dict[str, Any]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    previous_status = paper.review_status
    updates = request.model_dump(exclude_unset=True)
    diff: dict[str, dict[str, Any]] = {}
    for field_name, new_value in updates.items():
        old_value = getattr(paper, field_name)
        if old_value != new_value:
            diff[field_name] = {"before": old_value, "after": new_value}
            setattr(paper, field_name, new_value)
    corrected_metadata_fields = {
        field_name
        for field_name in diff
        if field_name not in {"review_status", "reviewer_notes"}
    }
    if corrected_metadata_fields:
        provenance = dict(paper.metadata_provenance or {})
        field_reviews = dict(paper.metadata_field_reviews or {})
        for field_name in corrected_metadata_fields:
            provenance[field_name] = {
                "source": "admin_review",
                "reviewer": "local_admin",
                "recorded_at": utc_now().isoformat(),
                "status": request.review_status or "reviewed",
            }
            field_reviews[field_name] = request.review_status or "reviewed"
        paper.metadata_provenance = provenance
        paper.metadata_field_reviews = field_reviews
    if "review_status" in updates or "reviewer_notes" in updates:
        apply_review_metadata(paper, paper.review_status, request.reviewer_notes)
    paper.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper",
        item_id=paper.paper_id,
        action=action_for_status(paper.review_status, corrected=bool(diff)),
        previous_status=previous_status,
        new_status=paper.review_status,
        notes=request.reviewer_notes,
        diff=diff,
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
) -> dict[str, Any]:
    artifact = session.get(PaperArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    previous_status = artifact.review_status
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(artifact, "review_status", request.review_status, diff)
    update_if_changed(artifact, "reviewer_notes", request.reviewer_notes, diff)
    if request.corrected_text is not None:
        update_if_changed(artifact, "corrected_text", request.corrected_text, diff)
    if request.corrected_json is not None:
        update_if_changed(artifact, "corrected_json", request.corrected_json, diff)
    apply_review_metadata(artifact, request.review_status, request.reviewer_notes)
    artifact.updated_at = utc_now()
    event = create_review_event(
        session,
        item_type="paper_artifact",
        item_id=artifact.artifact_id,
        action=action_for_status(request.review_status, corrected=bool(request.corrected_text or request.corrected_json)),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
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
) -> dict[str, Any]:
    recommendation = session.get(ThesisRecommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    previous_status = recommendation.review_status
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(recommendation, "review_status", request.review_status, diff)
    update_if_changed(recommendation, "reviewer_notes", request.reviewer_notes, diff)
    if request.corrected_recommendations_json is not None:
        update_if_changed(
            recommendation,
            "corrected_recommendations_json",
            {"items": request.corrected_recommendations_json}
            if isinstance(request.corrected_recommendations_json, list)
            else request.corrected_recommendations_json,
            diff,
        )
    apply_review_metadata(recommendation, request.review_status, request.reviewer_notes)
    event = create_review_event(
        session,
        item_type="thesis_recommendation",
        item_id=recommendation.recommendation_id,
        action=action_for_status(request.review_status, corrected=request.corrected_recommendations_json is not None),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
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
) -> dict[str, Any]:
    answer = session.get(RAGAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    previous_status = answer.review_status
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
    apply_review_metadata(answer, request.review_status, request.reviewer_notes)
    event = create_review_event(
        session,
        item_type="rag_answer",
        item_id=answer.answer_id,
        action=action_for_status(request.review_status, corrected=False),
        previous_status=previous_status,
        new_status=request.review_status,
        notes=request.reviewer_notes,
        diff=diff,
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
) -> dict[str, Any]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    previous_status = paper.review_status
    diff: dict[str, dict[str, Any]] = {}
    update_if_changed(paper, "review_status", request.review_status, diff)
    update_if_changed(paper, "reviewer_notes", request.reviewer_notes, diff)
    apply_review_metadata(paper, request.review_status, request.reviewer_notes)
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
    )
    session.add(paper)
    session.add(event)
    session.commit()
    session.refresh(paper)
    return {"paper": paper, "review_event": serialize_review_event(event)}


@router.get("/review-events")
def review_events(
    session: Annotated[Session, Depends(get_session)],
    item_type: Optional[str] = Query(default=None),
    item_id: Optional[str] = Query(default=None),
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


def apply_review_metadata(record: Any, review_status: str, reviewer_notes: Optional[str]) -> None:
    record.review_status = review_status
    record.reviewer_notes = reviewer_notes
    record.reviewed_at = utc_now()
    record.reviewed_by = "local_admin"


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
) -> ReviewEvent:
    return ReviewEvent(
        review_event_id=str(uuid.uuid4()),
        item_type=item_type,
        item_id=item_id,
        action=action,
        previous_status=previous_status,
        new_status=new_status,
        reviewer_name="local_admin",
        reviewer_notes=notes,
        diff_json=diff,
        created_at=utc_now(),
    )


def action_for_status(status: str, *, corrected: bool) -> str:
    if corrected:
        return "corrected"
    return {
        "approved": "approved",
        "rejected": "rejected",
        "reviewed": "reviewed",
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
        "reviewer_notes": event.reviewer_notes,
        "diff": event.diff_json,
        "created_at": format_dt(event.created_at),
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
    counts = {"needs_review": 0, "reviewed": 0, "approved": 0, "rejected": 0, "needs_reprocess": 0}
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
