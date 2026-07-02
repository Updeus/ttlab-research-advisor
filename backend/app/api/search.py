from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.db import get_session
from app.indexing.embedder import index_diagnostics
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.indexing.retriever import retrieve
from app.models import Chunk, Paper

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    session: Annotated[Session, Depends(get_session)],
    q: str = Query(..., min_length=1),
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid",
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
    semantic = index_diagnostics()
    searchable_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    searchable_papers = session.exec(
        select(func.count(func.distinct(Chunk.paper_id))).select_from(Chunk)
    ).one()
    return {
        "total_chunks": searchable_chunks,
        "searchable_chunks": searchable_chunks,
        "searchable_papers": searchable_papers,
        "chunks_indexed_for_keyword_search": keyword["keyword_indexed_chunks"],
        "chunks_indexed_for_semantic_search": semantic["semantic_indexed_chunks"],
        "keyword": keyword,
        "semantic": semantic,
        "embedding_provider": semantic["embedding_provider"],
        "embedding_dimensions": semantic["embedding_dimensions"],
        "index_path": semantic["index_path"],
        "index_status": semantic["index_status"],
        "last_indexed_timestamp": semantic["last_indexed_at"],
    }
