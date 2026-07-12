from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.db import get_session
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    eligible_chunks,
    index_diagnostics,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.indexing.retriever import retrieve
from app.models import Chunk, Paper

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    session: Annotated[Session, Depends(get_session)],
    q: str = Query(..., min_length=1),
    mode: Literal["keyword", "feature_hashing", "dense", "hybrid", "semantic"] = "hybrid",
    limit: int = Query(default=10, ge=1, le=50),
    paper_id: str | None = None,
    author: str | None = None,
    year: int | None = None,
    section: str | None = None,
) -> dict[str, object]:
    return retrieve(
        session,
        q,
        mode=mode,
        top_k=limit,
        paper_id=paper_id,
        author=author,
        year=year,
        section=section,
    )


@router.get("/search/diagnostics")
def search_diagnostics(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    keyword = keyword_diagnostics(session)
    feature_hashing = index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER)
    dense = index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER)
    raw_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    eligible = eligible_chunks(session)
    searchable_chunks = len(eligible)
    searchable_papers = len({chunk.paper_id for chunk in eligible})
    return {
        "total_chunks": raw_chunks,
        "raw_chunks": raw_chunks,
        "eligible_chunks": searchable_chunks,
        "searchable_chunks": searchable_chunks,
        "searchable_papers": searchable_papers,
        "chunks_indexed_for_keyword_search": keyword["keyword_indexed_chunks"],
        "chunks_indexed_for_feature_hashing": feature_hashing["indexed_chunks"],
        "chunks_indexed_for_dense_search": dense["indexed_chunks"],
        "chunks_indexed_for_semantic_search": feature_hashing["indexed_chunks"],  # legacy field
        "keyword": keyword,
        "feature_hashing": feature_hashing,
        "dense": dense,
        "semantic": feature_hashing,  # deprecated compatibility alias
        "embedding_provider": feature_hashing["embedding_provider"],
        "embedding_dimensions": feature_hashing["embedding_dimensions"],
        "index_path": feature_hashing["index_path"],
        "index_status": feature_hashing["index_status"],
        "last_indexed_timestamp": feature_hashing["last_indexed_at"],
    }
