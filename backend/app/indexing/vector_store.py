from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.embedder import (
    DEFAULT_PROVIDER,
    DenseProviderUnavailable,
    EmbeddingProvider,
    IndexIntegrityError,
    canonical_provider_name,
    cosine_similarity,
    default_index_path,
    get_provider,
    index_artifacts_available,
    load_validated_index,
)
from app.models import Chunk, Paper


@dataclass(frozen=True)
class VectorSearchContext:
    """One validated immutable index/provider pair for a frozen experiment."""

    provider_name: str
    index_path: Path
    active_index_path: Path
    active_manifest_path: Path
    generation_source: str
    payload: dict[str, Any]
    provider: EmbeddingProvider


def load_vector_search_context(
    session: Session,
    *,
    provider_name: str = DEFAULT_PROVIDER,
    index_path: Path | None = None,
) -> VectorSearchContext:
    canonical = canonical_provider_name(provider_name)
    resolved_path = (index_path or default_index_path(canonical)).resolve()
    if not index_artifacts_available(resolved_path):
        raise FileNotFoundError(
            f"{canonical} index is unavailable at {resolved_path}. Build and validate the complete index first."
        )
    payload, report = load_validated_index(
        session,
        index_path=resolved_path,
        provider_name=canonical,
    )
    provider = get_provider(canonical, dimensions=int(payload.get("dimensions") or 0) or None)
    return VectorSearchContext(
        provider_name=canonical,
        index_path=resolved_path,
        active_index_path=Path(str(report["index_path"])).resolve(),
        active_manifest_path=Path(str(report["manifest_path"])).resolve(),
        generation_source=str(report.get("generation_source") or "unknown"),
        payload=payload,
        provider=provider,
    )


def search_vector_store(
    session: Session,
    query: str,
    *,
    top_k: int = 10,
    provider_name: str = DEFAULT_PROVIDER,
    index_path: Path | None = None,
    paper_id: str | None = None,
    author: str | None = None,
    year: int | None = None,
    section: str | None = None,
    context: VectorSearchContext | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    canonical = canonical_provider_name(provider_name)
    resolved_path = (index_path or default_index_path(canonical)).resolve()
    if context is not None:
        if context.provider_name != canonical:
            raise ValueError(
                f"vector search context provider={context.provider_name} does not match requested provider={canonical}"
            )
        if index_path is not None and context.index_path != resolved_path:
            raise ValueError(
                f"vector search context path={context.index_path} does not match requested path={resolved_path}"
            )
        payload = context.payload
        provider = context.provider
    else:
        payload = None
        provider = None
    if not index_artifacts_available(resolved_path):
        return [], [
            (
                "The learned-dense index is unavailable; no vector results were returned."
                if canonical == "dense"
                else "The feature-hashing index is unavailable; no vector results were returned."
            )
        ]

    if payload is None or provider is None:
        # A present-but-inconsistent index is a data-integrity defect, not a normal
        # provider outage. Raise so startup/evaluation callers cannot use it.
        payload, _report = load_validated_index(
            session,
            index_path=resolved_path,
            provider_name=canonical,
        )
        try:
            provider = get_provider(canonical, dimensions=int(payload.get("dimensions") or 0) or None)
        except DenseProviderUnavailable:
            return [], ["The learned-dense provider is unavailable; no vector results were returned."]

    query_vector = provider.embed(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in payload.get("records", []):
        score = cosine_similarity(query_vector, record.get("embedding", []))
        if score <= 0:
            continue
        chunk = session.get(Chunk, record["chunk_id"])
        if chunk is None or not chunk_matches(chunk, paper_id=paper_id, section=section):
            continue
        paper = session.get(Paper, chunk.paper_id)
        if not paper_matches(paper, author=author, year=year):
            continue
        scored.append((score, build_vector_result(chunk, paper, score, canonical)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [result for _score, result in scored[:top_k]], []


def chunk_matches(chunk: Chunk, *, paper_id: str | None, section: str | None) -> bool:
    if paper_id and chunk.paper_id != paper_id:
        return False
    if section and (chunk.section or "").lower() != section.lower():
        return False
    return True


def paper_matches(paper: Paper | None, *, author: str | None, year: int | None) -> bool:
    if paper is None:
        return False
    if year is not None and paper.year != year:
        return False
    if author and not any(author.lower() in name.lower() for name in paper.authors):
        return False
    return True


def build_vector_result(chunk: Chunk, paper: Paper | None, score: float, provider_name: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "chunk_index": chunk.chunk_index,
        "paper_title": paper.title if paper else "",
        "authors": paper.authors if paper else [],
        "year": paper.year if paper else None,
        "venue": paper.venue if paper else None,
        "topics": paper.topics if paper else [],
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": chunk.text[:500],
        "text": chunk.text,
        "score": round(float(score), 6),
        "match_type": provider_name,
        "vector_provider": provider_name,
        "source": {
            "pdf_url": paper.pdf_url if paper else None,
            "post_url": paper.post_url if paper else None,
        },
    }


# Backward-compatible import name. New code should use build_vector_result.
build_semantic_result = build_vector_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search a validated local feature-hashing or learned-dense index.")
    subparsers = parser.add_subparsers(dest="command")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--provider", choices=["feature_hashing", "hashing", "dense"], default=DEFAULT_PROVIDER)
    search.add_argument("--index", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "search":
        build_parser().print_help()
        return
    create_db_and_tables()
    try:
        with Session(engine) as session:
            results, warnings = search_vector_store(
                session,
                args.query,
                top_k=args.top_k,
                provider_name=args.provider,
                index_path=Path(args.index) if args.index else None,
            )
    except IndexIntegrityError as exc:
        print(f"error=index_integrity_failure detail={exc}")
        raise SystemExit(1) from exc
    for warning in warnings:
        print(f"warning={warning}")
    for index, result in enumerate(results, start=1):
        print(
            f"{index}. score={result['score']:.4f} provider={result['vector_provider']} "
            f"paper={result['paper_title']} pages={result['page_start']}-{result['page_end']} "
            f"snippet={result['snippet']}"
        )


if __name__ == "__main__":
    main()
