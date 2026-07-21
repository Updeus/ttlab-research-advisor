from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    index_diagnostics,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics


def public_index_projection_health(
    session: Session,
    *,
    public_eligible_chunks: int,
) -> dict[str, dict[str, Any]]:
    """Return fail-closed public projection health over validated indexes.

    The authoritative indexes cover the technical evaluation corpus.  Public
    endpoints may report the size of the publishable projection, but must not
    infer that it is ready merely because publishable rows exist.  Conversely,
    this response deliberately omits technical-corpus counts and file paths.
    """

    keyword = keyword_diagnostics(session)
    feature = index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER)
    dense = index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER)
    return {
        "keyword": _project_health(keyword, public_eligible_chunks),
        "feature_hashing": {
            **_project_health(feature, public_eligible_chunks),
            "classification": "lexical_feature_hashing",
        },
        "dense": _project_health(dense, public_eligible_chunks),
    }


def _project_health(health: dict[str, Any], public_count: int) -> dict[str, Any]:
    underlying_status = str(health.get("status") or health.get("index_status") or "unknown")
    underlying_valid = underlying_status == "ready"
    if not underlying_valid:
        projection_status = "underlying_index_not_ready"
        indexed_chunks = 0
    elif public_count == 0:
        projection_status = "public_projection_empty"
        indexed_chunks = 0
    else:
        projection_status = "public_projection_ready"
        indexed_chunks = public_count
    return {
        "status": underlying_status,
        "projection_status": projection_status,
        "indexed_chunks": indexed_chunks,
        "public_eligible_chunks": public_count,
        "underlying_index_status": underlying_status,
        "underlying_representation_valid": underlying_valid,
        "underlying_error_count": len(health.get("errors") or []),
    }
