from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.config import Settings, get_settings
from app.db import get_session
from app.evaluation.dashboard import evaluation_files_present, latest_evaluation_timestamp
from app.indexing.embedder import eligible_chunks
from app.intelligence.topic_explorer import list_topics
from app.models import Author, AuthorTopic, Chunk, Paper, PaperArtifact, PaperTopic, RAGAnswer, ReviewEvent, ThesisRecommendation, Topic
from app.publication import (
    content_generation_diagnostics,
    is_local_demo_content,
    is_public_content,
    is_public_metadata,
    local_demo_corpus_preview_enabled,
    public_papers,
)
from app.api.index_health import public_index_projection_health

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers")
def list_papers(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[dict[str, object]]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    papers = list(session.exec(select(Paper)).all()) if demo_preview else public_papers(session)
    papers.sort(key=lambda item: (item.year or 0, item.title), reverse=True)
    return [serialize_public_paper(paper, demo_preview=demo_preview) for paper in papers]


@router.get("/papers/{paper_id}")
def get_paper(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    demo_preview = local_demo_corpus_preview_enabled(settings)
    if paper is None or (not demo_preview and not is_public_metadata(paper)):
        raise HTTPException(status_code=404, detail="Paper not found")
    return serialize_public_paper(paper, demo_preview=demo_preview)


@router.get("/papers/{paper_id}/extraction")
def get_extraction(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    demo_preview = local_demo_corpus_preview_enabled(settings)
    if (
        paper is None
        or not (
            is_public_content(session, paper)
            or (demo_preview and is_local_demo_content(session, paper))
        )
    ):
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
    settings: Annotated[Settings, Depends(get_settings)],
    full: bool = Query(default=False),
) -> list[dict[str, object]]:
    paper = session.get(Paper, paper_id)
    demo_preview = local_demo_corpus_preview_enabled(settings)
    if (
        paper is None
        or not (
            is_public_content(session, paper)
            or (demo_preview and is_local_demo_content(session, paper))
        )
    ):
        raise HTTPException(status_code=404, detail="Paper not found")
    if full:
        raise HTTPException(
            status_code=403,
            detail="Full extracted chunks are available only through the labeled admin publication preview",
        )
    chunks = session.exec(
        select(Chunk)
        .where(Chunk.paper_id == paper_id)
        .where(Chunk.extraction_generation_id == paper.extraction_generation_id)
        .order_by(Chunk.chunk_index)
    ).all()
    return [serialize_chunk(chunk, full=full) for chunk in chunks]


@router.get("/chunks/search")
def search_chunks(
    session: Annotated[Session, Depends(get_session)],
    q: str = Query(min_length=1, max_length=2_000),
    limit: int = Query(default=10, ge=1, le=50),
    full: bool = Query(default=False),
) -> list[dict[str, object]]:
    if not q.strip():
        return []
    if full:
        raise HTTPException(
            status_code=403,
            detail="Full extracted chunks are available only through the labeled admin publication preview",
        )
    pattern = f"%{q.strip()}%"
    chunks = session.exec(
        select(Chunk)
        .join(Paper, Paper.paper_id == Chunk.paper_id)
        .where(Paper.corpus_eligibility_status == "eligible")
        .where(Paper.review_status == "approved")
        .where(Paper.publication_status == "published")
        .where(Paper.rights_status == "cleared")
        .where(Paper.public_access_level == "searchable")
        .where(Paper.extraction_review_status == "approved")
        .where(Paper.extraction_generation_id.is_not(None))
        .where(Paper.chunk_generation_id.is_not(None))
        .where(Paper.chunk_extraction_generation_id == Paper.extraction_generation_id)
        .where(Paper.public_index_generation_id == Paper.chunk_generation_id)
        .where(Paper.chunk_count > 0)
        .where(Chunk.extraction_generation_id == Paper.extraction_generation_id)
        .where(Chunk.text.ilike(pattern))
        .order_by(Chunk.paper_id, Chunk.chunk_index)
        .limit(limit)
    ).all()
    papers_by_id = {
        paper_id: paper
        for paper_id in {chunk.paper_id for chunk in chunks}
        if (paper := session.get(Paper, paper_id)) is not None
        and content_generation_diagnostics(session, paper)["ready"]
    }
    return [serialize_chunk(chunk, full=full) for chunk in chunks if chunk.paper_id in papers_by_id]


@router.get("/stats")
def get_stats(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    papers = list(session.exec(select(Paper)).all()) if demo_preview else public_papers(session)
    public_ids = {paper.paper_id for paper in papers}
    total = len(papers)
    eligible = eligible_chunks(session, public_only=not demo_preview)
    searchable_papers = len({chunk.paper_id for chunk in eligible})
    searchable_chunks = len(eligible)
    index_health = public_index_projection_health(
        session,
        public_eligible_chunks=searchable_chunks,
    )
    total_chunks = searchable_chunks
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
    topic_result = list_topics(session, limit=10, demo_preview=demo_preview)
    top_topics = [
        (item["name"], item["paper_count"])
        for item in topic_result["items"]
    ]
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
        "topic_count": topic_result["total"],
        "author_count": len({author for paper in papers for author in paper.authors}),
        "paper_topic_links": session.exec(select(func.count()).select_from(PaperTopic).where(PaperTopic.paper_id.in_(public_ids))).one() if public_ids else 0,
        "author_topic_links": None,
        "papers_with_topics": session.exec(select(func.count(func.distinct(PaperTopic.paper_id))).select_from(PaperTopic).where(PaperTopic.paper_id.in_(public_ids))).one() if public_ids else 0,
        "authors_with_topics": None,
        "searchable_papers": searchable_papers,
        "searchable_chunks": searchable_chunks,
        "eligible_chunks": searchable_chunks,
        "raw_chunks": total_chunks,
        "keyword_indexed_chunks": index_health["keyword"]["indexed_chunks"],
        "semantic_indexed_chunks": None,
        "semantic_indexed_chunks_deprecated": "Use feature_hashing_indexed_chunks; feature hashing is lexical, not semantic.",
        "feature_hashing_indexed_chunks": index_health["feature_hashing"]["indexed_chunks"],
        "dense_indexed_chunks": index_health["dense"]["indexed_chunks"],
        "keyword_index_status": index_health["keyword"]["status"],
        "feature_hashing_index_status": index_health["feature_hashing"]["status"],
        "dense_index_status": index_health["dense"]["status"],
        "index_health": index_health,
        "default_ask_provider": settings.default_llm_provider,
        "evaluation_files_present": eval_files,
        "evaluation_last_run_at": latest_evaluation_timestamp(),
        "top_topics": top_topics,
        "recent_papers": [serialize_public_paper(paper, demo_preview=demo_preview) for paper in recent],
        "corpus_access_mode": "unreviewed_local_demo_preview" if demo_preview else "approved_public_projection",
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


def serialize_public_paper(paper: Paper, *, demo_preview: bool = False) -> dict[str, object]:
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
        "publication_status": paper.publication_status,
        "rights_status": paper.rights_status,
        "public_access_level": paper.public_access_level,
        "reviewed_at": paper.reviewed_at.isoformat() if paper.reviewed_at else None,
        "created_at": paper.created_at.isoformat(),
        "updated_at": paper.updated_at.isoformat(),
        "demo_preview": demo_preview,
    }


def count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
