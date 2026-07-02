from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.indexing.embedder import DEFAULT_INDEX_PATH, cosine_similarity, get_provider, load_embedding_index
from app.models import Chunk, Paper


def search_vector_store(
    session: Session,
    query: str,
    *,
    top_k: int = 10,
    provider_name: str = "hashing",
    index_path: Path = DEFAULT_INDEX_PATH,
    paper_id: str | None = None,
    author: str | None = None,
    year: int | None = None,
    section: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    payload = load_embedding_index(index_path)
    if payload is None:
        return [], [f"Semantic index missing at {index_path}. Run embedder index first."]
    if payload.get("provider") != provider_name:
        return [], [f"Semantic index provider is {payload.get('provider')}, not {provider_name}."]

    provider = get_provider(provider_name, dimensions=int(payload.get("dimensions") or 256))
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
        scored.append((score, build_semantic_result(chunk, paper, score)))
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


def build_semantic_result(chunk: Chunk, paper: Paper | None, score: float) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "paper_title": paper.title if paper else "",
        "authors": paper.authors if paper else [],
        "year": paper.year if paper else None,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": chunk.text[:500],
        "score": round(float(score), 6),
        "match_type": "semantic",
        "source": {
            "pdf_url": paper.pdf_url if paper else None,
            "post_url": paper.post_url if paper else None,
            "local_pdf_path": paper.local_pdf_path if paper else None,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search local vector indexes.")
    subparsers = parser.add_subparsers(dest="command")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--provider", default="hashing")
    search.add_argument("--index", default=str(DEFAULT_INDEX_PATH))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "search":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        results, warnings = search_vector_store(
            session,
            args.query,
            top_k=args.top_k,
            provider_name=args.provider,
            index_path=Path(args.index),
        )
    for warning in warnings:
        print(f"warning={warning}")
    for index, result in enumerate(results, start=1):
        print(
            f"{index}. score={result['score']:.4f} paper={result['paper_title']} "
            f"pages={result['page_start']}-{result['page_end']} snippet={result['snippet']}"
        )


if __name__ == "__main__":
    main()
