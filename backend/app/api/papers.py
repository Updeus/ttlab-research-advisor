from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.db import get_session
from app.evaluation.dashboard import evaluation_files_present, latest_evaluation_timestamp
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    eligible_chunks,
    index_diagnostics,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.models import Author, AuthorTopic, Chunk, Paper, PaperArtifact, PaperTopic, RAGAnswer, ReviewEvent, ThesisRecommendation, Topic
from app.security import AuthenticatedActor, get_optional_actor

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers")
def list_papers(session: Annotated[Session, Depends(get_session)]) -> list[dict[str, object]]:
    papers = session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all()
    return [serialize_public_paper(paper) for paper in papers]


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return serialize_public_paper(paper)


@router.get("/papers/{paper_id}/extraction")
def get_extraction(paper_id: str, session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    diagnostics = paper.extraction_diagnostics if isinstance(paper.extraction_diagnostics, dict) else {}
    return {
        "paper_id": paper.paper_id,
        "pdf_url": paper.pdf_url,
        "pdf_text_status": paper.pdf_text_status,
        "pdf_unavailability_reason": paper.pdf_unavailability_reason,
        "page_count": paper.page_count,
        "total_char_count": paper.total_char_count,
        "total_word_count": paper.total_word_count,
        "pages_with_text": paper.pages_with_text,
        "pages_without_text": paper.pages_without_text,
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
        "warnings": diagnostics.get("warnings", []),
        "chunk_count": paper.chunk_count,
    }


@router.get("/papers/{paper_id}/chunks")
def get_paper_chunks(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    full: bool = Query(default=False),
    actor: Annotated[AuthenticatedActor | None, Depends(get_optional_actor)] = None,
) -> list[dict[str, object]]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.corpus_eligibility_status != "eligible" and actor is None:
        raise HTTPException(status_code=404, detail="Paper chunks are not publicly available")
    if full and actor is None:
        raise HTTPException(status_code=403, detail="Full extracted chunks require reviewer authentication")
    chunks = session.exec(
        select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.chunk_index)
    ).all()
    return [serialize_chunk(chunk, full=full) for chunk in chunks]


@router.get("/chunks/search")
def search_chunks(
    session: Annotated[Session, Depends(get_session)],
    q: str = Query(min_length=1, max_length=2_000),
    limit: int = Query(default=10, ge=1, le=50),
    full: bool = Query(default=False),
    actor: Annotated[AuthenticatedActor | None, Depends(get_optional_actor)] = None,
) -> list[dict[str, object]]:
    if not q.strip():
        return []
    if full and actor is None:
        raise HTTPException(status_code=403, detail="Full extracted chunks require reviewer authentication")
    pattern = f"%{q.strip()}%"
    chunks = session.exec(
        select(Chunk)
        .join(Paper, Paper.paper_id == Chunk.paper_id)
        .where(Paper.corpus_eligibility_status == "eligible")
        .where(Chunk.text.ilike(pattern))
        .order_by(Chunk.paper_id, Chunk.chunk_index)
        .limit(limit)
    ).all()
    return [serialize_chunk(chunk, full=full) for chunk in chunks]


@router.get("/stats")
def get_stats(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    papers = list(session.exec(select(Paper)).all())
    total = session.exec(select(func.count()).select_from(Paper)).one()
    total_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    total_authors = session.exec(
        select(func.count())
        .select_from(Author)
        .where(Author.identity_status.notin_(["merged", "invalid"]))
    ).one()
    total_topics = session.exec(select(func.count()).select_from(Topic)).one()
    paper_topic_links = session.exec(select(func.count()).select_from(PaperTopic)).one()
    author_topic_links = session.exec(select(func.count()).select_from(AuthorTopic)).one()
    total_answers = session.exec(select(func.count()).select_from(RAGAnswer)).one()
    recommendation_runs = list(session.exec(select(ThesisRecommendation)).all())
    artifacts = list(session.exec(select(PaperArtifact)).all())
    review_events = list(session.exec(select(ReviewEvent)).all())
    eligible = eligible_chunks(session)
    searchable_papers = len({chunk.paper_id for chunk in eligible})
    searchable_chunks = len(eligible)
    keyword = keyword_diagnostics(session)
    feature_hashing = index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER)
    dense = index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER)
    with_pdf = sum(1 for paper in papers if paper.pdf_url)
    downloaded = sum(1 for paper in papers if paper.local_pdf_path)
    extracted = sum(1 for paper in papers if paper.pdf_text_status == "extracted")
    extraction_failed = sum(1 for paper in papers if paper.pdf_text_status in {"extraction_failed", "download_failed", "invalid_pdf"})
    no_text = sum(1 for paper in papers if paper.pdf_text_status == "no_text" or paper.possible_scanned_pdf)
    missing_pdf = sum(1 for paper in papers if paper.pdf_text_status == "missing_pdf")
    pdf_unavailability_reasons: dict[str, int] = {}
    for paper in papers:
        if paper.pdf_unavailability_reason:
            pdf_unavailability_reasons[paper.pdf_unavailability_reason] = (
                pdf_unavailability_reasons.get(paper.pdf_unavailability_reason, 0) + 1
            )
    topics: dict[str, int] = {}
    for paper in papers:
        for topic in paper.topics:
            topics[topic] = topics.get(topic, 0) + 1
    recent = sorted(papers, key=lambda item: (item.year or 0, item.created_at), reverse=True)[:5]
    eval_files = evaluation_files_present()
    return {
        "papers": total,
        "with_pdf_url": with_pdf,
        "downloaded_pdfs": downloaded,
        "extracted_pdfs": extracted,
        "extraction_failed": extraction_failed,
        "no_text_pdfs": no_text,
        "missing_pdf": missing_pdf,
        "pdf_unavailability_reasons": pdf_unavailability_reasons,
        "ocr_status_counts": count_values([paper.ocr_status for paper in papers]),
        "extraction_content_type_counts": count_values([paper.extraction_content_type for paper in papers]),
        "corpus_eligibility_status_counts": count_values([paper.corpus_eligibility_status for paper in papers]),
        "total_chunks": total_chunks,
        "topic_count": total_topics,
        "author_count": total_authors,
        "paper_topic_links": paper_topic_links,
        "author_topic_links": author_topic_links,
        "papers_with_topics": session.exec(select(func.count(func.distinct(PaperTopic.paper_id))).select_from(PaperTopic)).one(),
        "authors_with_topics": session.exec(select(func.count(func.distinct(AuthorTopic.author_id))).select_from(AuthorTopic)).one(),
        "searchable_papers": searchable_papers,
        "searchable_chunks": searchable_chunks,
        "eligible_chunks": searchable_chunks,
        "raw_chunks": total_chunks,
        "keyword_indexed_chunks": keyword["keyword_indexed_chunks"],
        "semantic_indexed_chunks": feature_hashing["indexed_chunks"],  # legacy field
        "feature_hashing_indexed_chunks": feature_hashing["indexed_chunks"],
        "dense_indexed_chunks": dense["indexed_chunks"],
        "feature_hashing_index_status": feature_hashing["status"],
        "dense_index_status": dense["status"],
        "total_ask_answers": total_answers,
        "grounded_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "grounded")).one(),
        "partial_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "partial")).one(),
        "unsupported_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "unsupported")).one(),
        "default_ask_provider": "ollama",
        "total_extension_recommendation_runs": len(recommendation_runs),
        "total_extension_ideas": sum(len(record.recommendations_json or []) for record in recommendation_runs),
        "grounded_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "grounded"),
        "partial_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "partial"),
        "unsupported_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "unsupported"),
        "total_paper_artifacts": len(artifacts),
        "papers_with_artifacts": len({artifact.paper_id for artifact in artifacts if artifact.generation_status == "generated"}),
        "podcast_scripts_generated": sum(1 for artifact in artifacts if artifact.artifact_type == "podcast_script" and artifact.generation_status == "generated"),
        "artifacts_needing_review": sum(1 for artifact in artifacts if artifact.review_status == "needs_review"),
        "admin_review_queue_count": (
            sum(1 for paper in papers if paper.review_status == "needs_review")
            + sum(1 for answer in session.exec(select(RAGAnswer)).all() if answer.review_status == "needs_review")
            + sum(1 for recommendation in recommendation_runs if recommendation.review_status == "needs_review")
            + sum(1 for artifact in artifacts if artifact.review_status == "needs_review")
        ),
        "papers_needing_review": sum(1 for paper in papers if paper.review_status == "needs_review"),
        "answers_needing_review": session.exec(
            select(func.count()).select_from(RAGAnswer).where(RAGAnswer.review_status == "needs_review")
        ).one(),
        "recommendations_needing_review": sum(1 for record in recommendation_runs if record.review_status == "needs_review"),
        "total_review_events": len(review_events),
        "latest_review_event_at": max((event.created_at for event in review_events), default=None).isoformat()
        if review_events
        else None,
        "evaluation_files_present": eval_files,
        "evaluation_last_run_at": latest_evaluation_timestamp(),
        "top_topics": sorted(topics.items(), key=lambda item: item[1], reverse=True)[:10],
        "recent_papers": [serialize_public_paper(paper) for paper in recent],
        "evaluation_status": "available" if any(eval_files.values()) else "not_started",
    }


def serialize_chunk(chunk: Chunk, *, full: bool) -> dict[str, object]:
    text = chunk.text if full else chunk.text[:500]
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "chunk_index": chunk.chunk_index,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section,
        "text": text,
        "snippet": text,
        "char_count": chunk.char_count,
        "word_count": chunk.word_count,
        "token_count_estimate": chunk.token_count_estimate,
        "source_hash": chunk.source_hash,
    }


def serialize_public_paper(paper: Paper) -> dict[str, object]:
    """Return publication metadata without local paths, raw records, or notes."""

    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "publication_date_raw": paper.publication_date_raw,
        "venue": paper.venue,
        "abstract": paper.abstract,
        "source_url": paper.source_url,
        "post_url": paper.post_url,
        "pdf_url": paper.pdf_url,
        "doi": paper.doi,
        "keywords": paper.keywords,
        "topics": paper.topics,
        "ingestion_status": paper.ingestion_status,
        "pdf_text_status": paper.pdf_text_status,
        "extraction_content_type": paper.extraction_content_type,
        "ocr_status": paper.ocr_status,
        "ocr_review_required": paper.ocr_review_required,
        "corpus_eligibility_status": paper.corpus_eligibility_status,
        "corpus_exclusion_reason": paper.corpus_exclusion_reason,
        "pdf_title_match_status": paper.pdf_title_match_status,
        "page_count": paper.page_count,
        "chunk_count": paper.chunk_count,
        "review_status": paper.review_status,
        "reviewed_at": paper.reviewed_at.isoformat() if paper.reviewed_at else None,
        "created_at": paper.created_at.isoformat(),
        "updated_at": paper.updated_at.isoformat(),
    }


def count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
