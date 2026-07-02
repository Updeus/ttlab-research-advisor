from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.db import get_session
from app.indexing.embedder import index_diagnostics
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.models import Chunk, Paper, RAGAnswer, ThesisRecommendation

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers", response_model=list[Paper])
def list_papers(session: Annotated[Session, Depends(get_session)]) -> list[Paper]:
    return list(session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all())


@router.get("/papers/{paper_id}", response_model=Paper)
def get_paper(paper_id: str, session: Annotated[Session, Depends(get_session)]) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("/papers/{paper_id}/extraction")
def get_extraction(paper_id: str, session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    diagnostics = paper.extraction_diagnostics if isinstance(paper.extraction_diagnostics, dict) else {}
    return {
        "paper_id": paper.paper_id,
        "pdf_url": paper.pdf_url,
        "local_pdf_path": paper.local_pdf_path,
        "pdf_text_status": paper.pdf_text_status,
        "page_count": paper.page_count,
        "total_char_count": paper.total_char_count,
        "total_word_count": paper.total_word_count,
        "pages_with_text": paper.pages_with_text,
        "pages_without_text": paper.pages_without_text,
        "possible_scanned_pdf": paper.possible_scanned_pdf,
        "warnings": diagnostics.get("warnings", []),
        "extraction_error": diagnostics.get("extraction_error"),
        "diagnostics": diagnostics,
        "extracted_json_path": paper.extracted_json_path,
        "extracted_text_path": paper.extracted_text_path,
        "chunk_count": paper.chunk_count,
    }


@router.get("/papers/{paper_id}/chunks")
def get_paper_chunks(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    full: bool = False,
) -> list[dict[str, object]]:
    if session.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    chunks = session.exec(
        select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.chunk_index)
    ).all()
    return [serialize_chunk(chunk, full=full) for chunk in chunks]


@router.get("/chunks/search")
def search_chunks(
    q: str,
    session: Annotated[Session, Depends(get_session)],
    limit: int = 10,
    full: bool = False,
) -> list[dict[str, object]]:
    if not q.strip():
        return []
    pattern = f"%{q.strip()}%"
    chunks = session.exec(
        select(Chunk).where(Chunk.text.ilike(pattern)).order_by(Chunk.paper_id, Chunk.chunk_index).limit(limit)
    ).all()
    return [serialize_chunk(chunk, full=full) for chunk in chunks]


@router.get("/stats")
def get_stats(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    papers = list(session.exec(select(Paper)).all())
    total = session.exec(select(func.count()).select_from(Paper)).one()
    total_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    total_answers = session.exec(select(func.count()).select_from(RAGAnswer)).one()
    recommendation_runs = list(session.exec(select(ThesisRecommendation)).all())
    searchable_papers = session.exec(select(func.count(func.distinct(Chunk.paper_id))).select_from(Chunk)).one()
    keyword = keyword_diagnostics(session)
    semantic = index_diagnostics()
    with_pdf = sum(1 for paper in papers if paper.pdf_url)
    downloaded = sum(1 for paper in papers if paper.local_pdf_path)
    extracted = sum(1 for paper in papers if paper.pdf_text_status == "extracted")
    extraction_failed = sum(1 for paper in papers if paper.pdf_text_status in {"extraction_failed", "download_failed", "invalid_pdf"})
    no_text = sum(1 for paper in papers if paper.pdf_text_status == "no_text" or paper.possible_scanned_pdf)
    missing_pdf = sum(1 for paper in papers if paper.pdf_text_status == "missing_pdf")
    topics: dict[str, int] = {}
    for paper in papers:
        for topic in paper.topics:
            topics[topic] = topics.get(topic, 0) + 1
    recent = sorted(papers, key=lambda item: (item.year or 0, item.created_at), reverse=True)[:5]
    return {
        "papers": total,
        "with_pdf_url": with_pdf,
        "downloaded_pdfs": downloaded,
        "extracted_pdfs": extracted,
        "extraction_failed": extraction_failed,
        "no_text_pdfs": no_text,
        "missing_pdf": missing_pdf,
        "total_chunks": total_chunks,
        "searchable_papers": searchable_papers,
        "searchable_chunks": total_chunks,
        "keyword_indexed_chunks": keyword["keyword_indexed_chunks"],
        "semantic_indexed_chunks": semantic["semantic_indexed_chunks"],
        "total_ask_answers": total_answers,
        "grounded_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "grounded")).one(),
        "partial_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "partial")).one(),
        "unsupported_answers": session.exec(select(func.count()).select_from(RAGAnswer).where(RAGAnswer.grounding_status == "unsupported")).one(),
        "default_ask_provider": "offline_extractive",
        "total_extension_recommendation_runs": len(recommendation_runs),
        "total_extension_ideas": sum(len(record.recommendations_json or []) for record in recommendation_runs),
        "grounded_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "grounded"),
        "partial_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "partial"),
        "unsupported_extension_runs": sum(1 for record in recommendation_runs if record.grounding_status == "unsupported"),
        "top_topics": sorted(topics.items(), key=lambda item: item[1], reverse=True)[:10],
        "recent_papers": recent,
        "evaluation_status": "not_started",
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
