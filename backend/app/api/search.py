from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from app.db import get_session
from app.config import Settings, get_settings
from app.api.index_health import public_index_projection_health
from app.indexing.embedder import eligible_chunks
from app.indexing.retriever import retrieve, sanitize_public_retrieval_warnings
from app.models import Chunk, Paper
from app.publication import local_demo_corpus_preview_enabled

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    q: str = Query(..., min_length=1, max_length=2_000),
    mode: Literal["keyword", "feature_hashing", "dense", "hybrid"] = "keyword",
    limit: int = Query(default=10, ge=1, le=50),
    paper_id: str | None = Query(default=None, max_length=200),
    author: str | None = Query(default=None, max_length=300),
    year: int | None = None,
    section: str | None = Query(default=None, max_length=100),
) -> dict[str, object]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    result = retrieve(
        session,
        q,
        mode=mode,
        top_k=limit,
        paper_id=paper_id,
        author=author,
        year=year,
        section=section,
        scope="technical" if demo_preview else "public",
    )
    result["warnings"] = sanitize_public_retrieval_warnings(list(result.get("warnings") or []))
    if demo_preview:
        result["warnings"].append(
            "Local demo preview: results come from technically eligible but not necessarily publication-approved papers."
        )
    result["demo_preview"] = demo_preview
    return result


@router.get("/search/diagnostics")
def search_diagnostics(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    eligible = eligible_chunks(session, public_only=not demo_preview)
    searchable_chunks = len(eligible)
    searchable_papers = len({chunk.paper_id for chunk in eligible})
    index_health = public_index_projection_health(
        session,
        public_eligible_chunks=searchable_chunks,
    )
    return {
        "total_chunks": searchable_chunks,
        "raw_chunks": None,
        "eligible_chunks": searchable_chunks,
        "searchable_chunks": searchable_chunks,
        "searchable_papers": searchable_papers,
        "chunks_indexed_for_keyword_search": index_health["keyword"]["indexed_chunks"],
        "chunks_indexed_for_feature_hashing": index_health["feature_hashing"]["indexed_chunks"],
        "chunks_indexed_for_dense_search": index_health["dense"]["indexed_chunks"],
        "chunks_indexed_for_semantic_search": None,
        "semantic_search_deprecation": "Feature hashing is a lexical baseline; use feature_hashing explicitly.",
        "keyword": index_health["keyword"],
        "feature_hashing": index_health["feature_hashing"],
        "dense": index_health["dense"],
        "embedding_provider": None,
        "embedding_dimensions": None,
        "index_status": index_health["keyword"]["status"],
        "last_indexed_timestamp": None,
        "corpus_access_mode": "unreviewed_local_demo_preview" if demo_preview else "approved_public_projection",
    }
