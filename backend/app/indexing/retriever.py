from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Literal

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    canonical_provider_name,
    index_diagnostics,
)
from app.indexing.keyword_search import SearchFilters, enrich_keyword_results, search_keyword
from app.indexing.vector_store import search_vector_store

RetrievalMode = Literal["keyword", "feature_hashing", "dense", "hybrid", "semantic"]

STOPWORDS = {
    "about",
    "also",
    "and",
    "are",
    "can",
    "could",
    "discuss",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "main",
    "papers",
    "paper",
    "read",
    "relate",
    "relates",
    "research",
    "show",
    "that",
    "the",
    "this",
    "to",
    "want",
    "what",
    "which",
    "who",
    "with",
}

QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "rag": ("retrieval augmented generation", "retrieval-augmented generation", "grounded generation"),
    "retrieval augmented generation": ("rag", "retrieval-augmented generation", "grounded generation"),
    "ai": ("artificial intelligence", "machine learning", "generative ai", "language model"),
    "artificial intelligence": ("ai",),
    "ml": ("machine learning",),
    "machine learning": ("ml",),
    "agriculture": ("crops", "crop", "cocoa", "plantation", "biomass", "deforestation", "drone", "farming"),
    "agricultural": ("agriculture", "crops", "crop", "cocoa", "plantation", "biomass", "deforestation", "drone"),
    "crop": ("agriculture", "crops", "cocoa", "plantation", "farming"),
    "crops": ("agriculture", "crop", "cocoa", "plantation", "farming"),
    "research discovery": ("publication archive", "academic research", "paper collection", "summarization", "podcasting"),
    "web app": ("web application", "dashboard", "platform"),
    "web application": ("web app", "dashboard", "platform"),
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
    provider: str = "auto",
    index_path: Path | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    warnings: list[str] = []
    filters = SearchFilters(paper_id=paper_id, author=author, year=year, section=section)
    expanded_query, query_expansions = expand_query(query)

    keyword_results: list[dict[str, Any]] = []
    vector_results: list[dict[str, Any]] = []
    vector_provider, vector_index_path, provider_warnings = resolve_vector_backend(
        session,
        mode=mode,
        provider=provider,
        index_path=index_path,
    )
    warnings.extend(provider_warnings)

    if mode in {"keyword", "hybrid"}:
        raw_keyword = search_keyword(session, expanded_query, top_k=max(top_k * 3, top_k), filters=filters)
        keyword_results = enrich_keyword_results(session, raw_keyword, filters=filters)
    if mode in {"feature_hashing", "dense", "semantic", "hybrid"}:
        vector_results, vector_warnings = search_vector_store(
            session,
            expanded_query,
            top_k=max(top_k * 3, top_k),
            provider_name=vector_provider,
            index_path=vector_index_path,
            paper_id=paper_id,
            author=author,
            year=year,
            section=section,
        )
        warnings.extend(vector_warnings)

    selection_k = max(top_k * 3, top_k) if has_strong_topical_constraint(expanded_query) else top_k

    if mode == "keyword":
        results = [
            format_result(result, rank, keyword=result["score"], semantic=0.0, query=expanded_query, include_text=include_text)
            for rank, result in enumerate(keyword_results[:selection_k], start=1)
        ]
    elif mode in {"feature_hashing", "dense", "semantic"}:
        results = [
            format_result(
                result,
                rank,
                keyword=0.0,
                semantic=result["score"],
                vector_provider=vector_provider,
                query=expanded_query,
                include_text=include_text,
            )
            for rank, result in enumerate(vector_results[:selection_k], start=1)
        ]
    else:
        results = combine_hybrid(
            keyword_results,
            vector_results,
            top_k=selection_k,
            query=expanded_query,
            vector_provider=vector_provider,
            include_text=include_text,
        )
    results = apply_topical_constraints(results, expanded_query, top_k=top_k)

    return {
        "query": query,
        "expanded_query": expanded_query,
        "query_expansions": query_expansions,
        "mode": mode,
        "result_count": len(results),
        "results": results,
        "warnings": warnings,
        "vector_provider": vector_provider if mode != "keyword" else None,
        "retrieval_strategy": "expanded_metadata_section_diverse" if query_expansions else "metadata_section_diverse",
    }


def resolve_vector_backend(
    session: Session,
    *,
    mode: RetrievalMode,
    provider: str,
    index_path: Path | None,
) -> tuple[str, Path | None, list[str]]:
    if mode == "semantic":
        return (
            FEATURE_HASHING_PROVIDER,
            index_path or DEFAULT_INDEX_PATH,
            ["Retrieval mode 'semantic' is a deprecated alias for the lexical feature-hashing baseline; use 'feature_hashing'."],
        )
    if mode == "feature_hashing":
        return FEATURE_HASHING_PROVIDER, index_path or DEFAULT_INDEX_PATH, []
    if mode == "dense":
        return DENSE_PROVIDER, index_path or DENSE_INDEX_PATH, []
    if provider != "auto":
        canonical = canonical_provider_name(provider)
        return canonical, index_path, []
    if index_path is not None:
        # A caller-supplied legacy path is assumed to be the hashing baseline.
        return FEATURE_HASHING_PROVIDER, index_path, []
    dense_health = index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER)
    if dense_health["status"] == "ready":
        return DENSE_PROVIDER, DENSE_INDEX_PATH, []
    return (
        FEATURE_HASHING_PROVIDER,
        DEFAULT_INDEX_PATH,
        ["Complete learned-dense index unavailable; hybrid retrieval explicitly fell back to feature hashing."],
    )


def combine_hybrid(
    keyword_results: list[dict[str, Any]],
    semantic_results: list[dict[str, Any]],
    *,
    top_k: int,
    query: str,
    vector_provider: str = FEATURE_HASHING_PROVIDER,
    include_text: bool = False,
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
        entry["evidence_quality"] = evidence_quality_score(base)
        entry["topical_alignment"] = topical_alignment_score(base, query)
        entry["base_combined"] = min(
            1.0,
            max(
                0.0,
                base_score
                + entry["metadata"]
                + entry["section_boost"]
                + entry["evidence_quality"]
                + entry["topical_alignment"],
            ),
        )

    ranked = sorted(combined.values(), key=lambda entry: entry["base_combined"], reverse=True)
    diversified = diversify_ranked_entries(ranked, top_k=top_k)
    return [
        format_result(
            entry["base"],
            rank,
            keyword=entry["keyword"],
            semantic=entry["semantic"],
            vector_provider=vector_provider,
            metadata=entry["metadata"],
            section=entry["section_boost"],
            combined_override=entry["diversified_score"],
            query=query,
            include_text=include_text,
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
    vector_provider: str | None = None,
    query: str = "",
    metadata: float | None = None,
    section: float | None = None,
    combined_override: float | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    metadata_score_value = metadata if metadata is not None else metadata_score(result, query)
    section_boost_value = section if section is not None else section_boost(str(result.get("section") or ""), query)
    evidence_quality_value = evidence_quality_score(result)
    topical_alignment_value = topical_alignment_score(result, query)
    combined = (
        combined_override
        if combined_override is not None
        else min(
            1.0,
            max(
                0.0,
                keyword * 0.42
                + semantic * 0.48
                + metadata_score_value
                + section_boost_value
                + evidence_quality_value
                + topical_alignment_value,
            ),
        )
    )
    formatted = {
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
            "vector": round(semantic, 6),
            "vector_provider": vector_provider,
            "metadata": round(metadata_score_value, 6),
            "section_boost": round(section_boost_value, 6),
            "evidence_quality": round(evidence_quality_value, 6),
            "topical_alignment": round(topical_alignment_value, 6),
            "combined": round(combined if combined else normalize_score(result.get("score", 0.0)), 6),
        },
        "source": {
            key: value
            for key, value in result.get("source", {"pdf_url": None, "post_url": None}).items()
            if key in {"pdf_url", "post_url"}
        },
    }
    if include_text:
        formatted["text"] = result.get("text", "")
    return formatted


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
    return {
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9]+", query)
        if len(token) > 1 and token.lower() not in STOPWORDS
    }


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


def evidence_quality_score(result: dict[str, Any]) -> float:
    text = str(result.get("text") or result.get("snippet") or "")
    if not text:
        return -0.04
    lowered = text.lower()
    section = str(result.get("section") or "").lower()
    penalty = 0.0
    if "@" in text:
        penalty += 0.035
    if any(marker in lowered for marker in ("proceedings of", "annual conference", "conference on", " arxiv", " doi", " et al")):
        penalty += 0.085
    if any(marker in lowered[:160] for marker in ("master's thesis", "master’s thesis", "references", "funding no funds", "declarations conflict")):
        penalty += 0.12
    if any(marker in section for marker in ("reference", "bibliography")):
        penalty += 0.09
    if any(marker in lowered for marker in ("abstract—", "abstract-", "department of", "university of")):
        penalty += 0.025
    if len(re.findall(r"\[[0-9]+\]", text)) >= 2:
        penalty += 0.09
    if len(text.split()) < 18:
        penalty += 0.025
    bonus = 0.0
    if any(marker in lowered for marker in ("we ", "this paper", "this research", "results", "demonstrates", "proposes", "evaluat")):
        bonus += 0.025
    if any(marker in lowered for marker in ("limitations and future work", "future work", "limitations", "future research")):
        bonus += 0.12
    return max(-0.22, min(0.08, bonus - penalty))


def topical_alignment_score(result: dict[str, Any], query: str) -> float:
    lowered_query = query.lower()
    text = " ".join(
        [
            str(result.get("paper_title") or ""),
            str(result.get("venue") or ""),
            " ".join(str(topic) for topic in result.get("topics", [])),
            str(result.get("snippet") or ""),
            str(result.get("text") or "")[:1200],
        ]
    ).lower()
    score = 0.0
    if "rag" in lowered_query or "retrieval augmented generation" in lowered_query or "retrieval-augmented generation" in lowered_query:
        has_rag_signal = any(term in text for term in ("rag", "retrieval augmented", "retrieval-augmented"))
        score += 0.055 if has_rag_signal else -0.18
    if "agriculture" in lowered_query or "agricultural" in lowered_query:
        agriculture_terms = ("agriculture", "agricultural", "crop", "crops", "cocoa", "plantation", "biomass", "deforestation", "drone", "weed", "water stress")
        if any(term in text for term in agriculture_terms):
            score += 0.15
        elif " or " not in f" {lowered_query} ":
            score -= 0.08
    if any(term in lowered_query for term in ("web app", "web application", "research discovery", "publication archive")):
        if any(term in text for term in ("web application", "platform", "publication", "research", "summarization", "podcasting", "dashboard")):
            score += 0.06
    if any(term in lowered_query for term in ("limitation", "future work", "future research", "challenge", "extend")):
        if any(term in text for term in ("limitation", "limitations", "future work", "future research", "challenge", "improve", "extend", "not one-size")):
            score += 0.09
    return max(-0.22, min(0.1, score))


def apply_topical_constraints(results: list[dict[str, Any]], query: str, *, top_k: int) -> list[dict[str, Any]]:
    lowered_query = query.lower()
    if not has_strong_topical_constraint(query):
        return results
    filtered = [result for result in results if has_rag_signal(result)]
    if len(filtered) < min(2, top_k):
        return results
    for index, result in enumerate(filtered[:top_k], start=1):
        result["rank"] = index
    return filtered[:top_k]


def has_strong_topical_constraint(query: str) -> bool:
    lowered_query = query.lower()
    return "rag" in lowered_query or "retrieval augmented generation" in lowered_query or "retrieval-augmented generation" in lowered_query


def has_rag_signal(result: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(result.get("paper_title") or ""),
            str(result.get("snippet") or ""),
            str(result.get("text") or "")[:1200],
        ]
    ).lower()
    return bool(re.search(r"(?<![a-z0-9])rag(?![a-z0-9])", text)) or "retrieval augmented" in text or "retrieval-augmented" in text


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
    parser = argparse.ArgumentParser(description="Retrieve source chunks by keyword, feature hashing, learned dense, or hybrid mode.")
    subparsers = parser.add_subparsers(dest="command")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["keyword", "feature_hashing", "dense", "hybrid", "semantic"], default="hybrid")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--provider", choices=["auto", "feature_hashing", "hashing", "dense"], default="auto")
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
