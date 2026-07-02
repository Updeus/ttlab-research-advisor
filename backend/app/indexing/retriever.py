from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Literal

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.embedder import DEFAULT_INDEX_PATH
from app.indexing.keyword_search import SearchFilters, enrich_keyword_results, search_keyword
from app.indexing.vector_store import search_vector_store

RetrievalMode = Literal["keyword", "semantic", "hybrid"]


def retrieve(
    session: Session,
    query: str,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int = 10,
    paper_id: str | None = None,
    author: str | None = None,
    year: int | None = None,
    section: str | None = None,
    provider: str = "hashing",
    index_path: Path = DEFAULT_INDEX_PATH,
) -> dict[str, Any]:
    warnings: list[str] = []
    filters = SearchFilters(paper_id=paper_id, author=author, year=year, section=section)

    keyword_results: list[dict[str, Any]] = []
    semantic_results: list[dict[str, Any]] = []

    if mode in {"keyword", "hybrid"}:
        raw_keyword = search_keyword(session, query, top_k=max(top_k * 3, top_k), filters=filters)
        keyword_results = enrich_keyword_results(session, raw_keyword, filters=filters)
    if mode in {"semantic", "hybrid"}:
        semantic_results, semantic_warnings = search_vector_store(
            session,
            query,
            top_k=max(top_k * 3, top_k),
            provider_name=provider,
            index_path=index_path,
            paper_id=paper_id,
            author=author,
            year=year,
            section=section,
        )
        warnings.extend(semantic_warnings)

    if mode == "keyword":
        results = [format_result(result, rank, keyword=result["score"], semantic=0.0) for rank, result in enumerate(keyword_results[:top_k], start=1)]
    elif mode == "semantic":
        results = [format_result(result, rank, keyword=0.0, semantic=result["score"]) for rank, result in enumerate(semantic_results[:top_k], start=1)]
    else:
        results = combine_hybrid(keyword_results, semantic_results, top_k=top_k)

    return {
        "query": query,
        "mode": mode,
        "result_count": len(results),
        "results": results,
        "warnings": warnings,
    }


def combine_hybrid(
    keyword_results: list[dict[str, Any]],
    semantic_results: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for result in keyword_results:
        entry = combined.setdefault(result["chunk_id"], {"base": result, "keyword": 0.0, "semantic": 0.0})
        entry["keyword"] = max(entry["keyword"], normalize_score(result["score"]))
    for result in semantic_results:
        entry = combined.setdefault(result["chunk_id"], {"base": result, "keyword": 0.0, "semantic": 0.0})
        entry["semantic"] = max(entry["semantic"], normalize_score(result["score"]))
        if not entry["base"].get("paper_title"):
            entry["base"] = result

    ranked = sorted(
        combined.values(),
        key=lambda entry: (entry["keyword"] * 0.45 + entry["semantic"] * 0.55, entry["keyword"], entry["semantic"]),
        reverse=True,
    )
    return [
        format_result(
            entry["base"],
            rank,
            keyword=entry["keyword"],
            semantic=entry["semantic"],
        )
        for rank, entry in enumerate(ranked[:top_k], start=1)
    ]


def normalize_score(score: float) -> float:
    return max(0.0, min(float(score), 1.0))


def format_result(result: dict[str, Any], rank: int, *, keyword: float, semantic: float) -> dict[str, Any]:
    combined = keyword * 0.45 + semantic * 0.55
    return {
        "rank": rank,
        "paper_id": result["paper_id"],
        "paper_title": result.get("paper_title", ""),
        "authors": result.get("authors", []),
        "year": result.get("year"),
        "chunk_id": result["chunk_id"],
        "section": result.get("section"),
        "page_start": result.get("page_start"),
        "page_end": result.get("page_end"),
        "snippet": result.get("snippet", ""),
        "scores": {
            "keyword": round(keyword, 6),
            "semantic": round(semantic, 6),
            "combined": round(combined if combined else normalize_score(result.get("score", 0.0)), 6),
        },
        "source": result.get("source", {"pdf_url": None, "post_url": None, "local_pdf_path": None}),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieve source chunks by keyword, semantic, or hybrid mode.")
    subparsers = parser.add_subparsers(dest="command")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--provider", default="hashing")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "search":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        response = retrieve(
            session,
            args.query,
            mode=args.mode,
            top_k=args.top_k,
            provider=args.provider,
        )
    for warning in response["warnings"]:
        print(f"warning={warning}")
    for result in response["results"]:
        print(
            f"{result['rank']}. score={result['scores']['combined']:.4f} "
            f"paper={result['paper_title']} pages={result['page_start']}-{result['page_end']} "
            f"snippet={result['snippet']}"
        )


if __name__ == "__main__":
    main()
