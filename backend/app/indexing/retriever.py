from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Literal

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.embedder import DEFAULT_INDEX_PATH
from app.indexing.keyword_search import SearchFilters, enrich_keyword_results, search_keyword
from app.indexing.vector_store import search_vector_store

RetrievalMode = Literal["keyword", "semantic", "hybrid"]

QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "rag": ("retrieval augmented generation", "retrieval-augmented generation", "grounded generation"),
    "retrieval augmented generation": ("rag", "retrieval-augmented generation", "grounded generation"),
    "ai": ("artificial intelligence", "machine intelligence"),
    "artificial intelligence": ("ai",),
    "ml": ("machine learning",),
    "machine learning": ("ml",),
    "optimization": ("optimisation", "optimize", "optimise"),
    "optimisation": ("optimization", "optimize", "optimise"),
    "llm": ("large language model", "language model"),
    "large language model": ("llm", "language model"),
}


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
    expanded_query, query_expansions = expand_query(query)

    keyword_results: list[dict[str, Any]] = []
    semantic_results: list[dict[str, Any]] = []

    if mode in {"keyword", "hybrid"}:
        raw_keyword = search_keyword(session, expanded_query, top_k=max(top_k * 3, top_k), filters=filters)
        keyword_results = enrich_keyword_results(session, raw_keyword, filters=filters)
    if mode in {"semantic", "hybrid"}:
        semantic_results, semantic_warnings = search_vector_store(
            session,
            expanded_query,
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
        results = [
            format_result(result, rank, keyword=result["score"], semantic=0.0, query=expanded_query)
            for rank, result in enumerate(keyword_results[:top_k], start=1)
        ]
    elif mode == "semantic":
        results = [
            format_result(result, rank, keyword=0.0, semantic=result["score"], query=expanded_query)
            for rank, result in enumerate(semantic_results[:top_k], start=1)
        ]
    else:
        results = combine_hybrid(keyword_results, semantic_results, top_k=top_k, query=expanded_query)

    return {
        "query": query,
        "expanded_query": expanded_query,
        "query_expansions": query_expansions,
        "mode": mode,
        "result_count": len(results),
        "results": results,
        "warnings": warnings,
        "retrieval_strategy": "expanded_metadata_section_diverse" if query_expansions else "metadata_section_diverse",
    }


def combine_hybrid(
    keyword_results: list[dict[str, Any]],
    semantic_results: list[dict[str, Any]],
    *,
    top_k: int,
    query: str,
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

    for entry in combined.values():
        base = entry["base"]
        base_score = entry["keyword"] * 0.42 + entry["semantic"] * 0.48
        entry["metadata"] = metadata_score(base, query)
        entry["section_boost"] = section_boost(str(base.get("section") or ""), query)
        entry["base_combined"] = min(1.0, base_score + entry["metadata"] + entry["section_boost"])

    ranked = sorted(combined.values(), key=lambda entry: entry["base_combined"], reverse=True)
    diversified = diversify_ranked_entries(ranked, top_k=top_k)
    return [
        format_result(
            entry["base"],
            rank,
            keyword=entry["keyword"],
            semantic=entry["semantic"],
            metadata=entry["metadata"],
            section=entry["section_boost"],
            combined_override=entry["diversified_score"],
            query=query,
        )
        for rank, entry in enumerate(diversified, start=1)
    ]


def normalize_score(score: float) -> float:
    return max(0.0, min(float(score), 1.0))


def format_result(
    result: dict[str, Any],
    rank: int,
    *,
    keyword: float,
    semantic: float,
    query: str = "",
    metadata: float | None = None,
    section: float | None = None,
    combined_override: float | None = None,
) -> dict[str, Any]:
    metadata_score_value = metadata if metadata is not None else metadata_score(result, query)
    section_boost_value = section if section is not None else section_boost(str(result.get("section") or ""), query)
    combined = combined_override if combined_override is not None else min(1.0, keyword * 0.42 + semantic * 0.48 + metadata_score_value + section_boost_value)
    return {
        "rank": rank,
        "paper_id": result["paper_id"],
        "paper_title": result.get("paper_title", ""),
        "authors": result.get("authors", []),
        "year": result.get("year"),
        "venue": result.get("venue"),
        "topics": result.get("topics", []),
        "chunk_id": result["chunk_id"],
        "chunk_index": result.get("chunk_index"),
        "section": result.get("section"),
        "page_start": result.get("page_start"),
        "page_end": result.get("page_end"),
        "snippet": result.get("snippet", ""),
        "scores": {
            "keyword": round(keyword, 6),
            "semantic": round(semantic, 6),
            "metadata": round(metadata_score_value, 6),
            "section_boost": round(section_boost_value, 6),
            "combined": round(combined if combined else normalize_score(result.get("score", 0.0)), 6),
        },
        "source": result.get("source", {"pdf_url": None, "post_url": None, "local_pdf_path": None}),
    }


def expand_query(query: str) -> tuple[str, list[str]]:
    lowered = query.lower()
    additions: list[str] = []
    for phrase, expansions in QUERY_EXPANSIONS.items():
        if phrase in lowered:
            for expansion in expansions:
                if expansion not in lowered and expansion not in additions:
                    additions.append(expansion)
    if not additions:
        return query, []
    return f"{query} {' '.join(additions)}", additions


def query_tokens(query: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z0-9]+", query) if len(token) > 1}


def metadata_score(result: dict[str, Any], query: str) -> float:
    tokens = query_tokens(query)
    if not tokens:
        return 0.0
    metadata_text = " ".join(
        [
            str(result.get("paper_title") or ""),
            str(result.get("venue") or ""),
            " ".join(str(author) for author in result.get("authors", [])),
            " ".join(str(topic) for topic in result.get("topics", [])),
        ]
    )
    metadata_tokens = query_tokens(metadata_text)
    if not metadata_tokens:
        return 0.0
    coverage = len(tokens.intersection(metadata_tokens)) / len(tokens)
    title_tokens = query_tokens(str(result.get("paper_title") or ""))
    title_bonus = 0.04 if tokens.intersection(title_tokens) else 0.0
    return min(0.16, coverage * 0.12 + title_bonus)


def section_boost(section_name: str, query: str) -> float:
    section = section_name.lower()
    lowered = query.lower()
    if not section:
        return 0.0
    if any(term in lowered for term in ("method", "approach", "implementation", "algorithm")) and any(
        term in section for term in ("method", "approach", "implementation")
    ):
        return 0.08
    if any(term in lowered for term in ("future", "extend", "extension", "limitation", "challenge")) and any(
        term in section for term in ("future", "limitation", "discussion", "conclusion")
    ):
        return 0.08
    if any(term in lowered for term in ("evaluate", "result", "experiment", "metric")) and any(
        term in section for term in ("result", "evaluation", "experiment")
    ):
        return 0.07
    if any(term in section for term in ("abstract", "introduction", "conclusion")):
        return 0.035
    return 0.0


def diversify_ranked_entries(entries: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    remaining = [dict(entry) for entry in entries]
    while remaining and len(selected) < top_k:
        best_index = 0
        best_score = -1.0
        for index, entry in enumerate(remaining):
            penalty = diversity_penalty(entry, selected)
            score = max(0.0, float(entry["base_combined"]) - penalty)
            if score > best_score:
                best_score = score
                best_index = index
        picked = remaining.pop(best_index)
        picked["diversified_score"] = round(best_score, 6)
        selected.append(picked)
    return selected


def diversity_penalty(entry: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    if not selected:
        return 0.0
    paper_id = entry["base"].get("paper_id")
    chunk_index = entry["base"].get("chunk_index")
    penalty = 0.0
    for chosen in selected:
        chosen_base = chosen["base"]
        if chosen_base.get("paper_id") != paper_id:
            continue
        penalty += 0.045
        chosen_index = chosen_base.get("chunk_index")
        if isinstance(chunk_index, int) and isinstance(chosen_index, int) and abs(chunk_index - chosen_index) <= 1:
            penalty += 0.04
    return min(0.16, penalty)


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
