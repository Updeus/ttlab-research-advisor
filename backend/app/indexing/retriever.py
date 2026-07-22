from __future__ import annotations

import argparse
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal, Mapping

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    canonical_provider_name,
    eligible_chunks,
    index_diagnostics,
)
from app.indexing.keyword_search import SearchFilters, enrich_keyword_results, search_keyword
from app.indexing.vector_store import search_vector_store
from app.models import Paper
from app.publication import is_public_content

RetrievalMode = Literal["keyword", "feature_hashing", "dense", "hybrid"]
RetrievalScope = Literal["public", "technical"]


@dataclass(frozen=True)
class RetrieverConfig:
    """Explicit, serializable controls for retrieval and re-ranking.

    Defaults reproduce the pre-experiment runtime heuristic. Experiments pass
    their own immutable configurations so a named baseline cannot silently
    inherit query expansion or heuristic re-ranking terms.
    """

    enable_query_expansion: bool = True
    enable_metadata_boost: bool = True
    enable_section_boost: bool = True
    enable_evidence_adjustment: bool = True
    enable_topic_adjustment: bool = True
    enable_diversity_penalty: bool = True
    keyword_weight: float = 0.42
    vector_weight: float = 0.48
    metadata_scale: float = 1.0
    section_scale: float = 1.0
    evidence_scale: float = 1.0
    topic_scale: float = 1.0
    diversity_scale: float = 1.0
    candidate_multiplier: int = 3

    def __post_init__(self) -> None:
        numeric = (
            "keyword_weight",
            "vector_weight",
            "metadata_scale",
            "section_scale",
            "evidence_scale",
            "topic_scale",
            "diversity_scale",
        )
        for name in numeric:
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if self.keyword_weight == 0.0 and self.vector_weight == 0.0:
            raise ValueError("at least one base retrieval weight must be positive")
        if self.candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RetrieverConfig":
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown retriever configuration fields: {unknown}")
        return cls(**dict(value))


DEFAULT_RETRIEVER_CONFIG = RetrieverConfig()
BASELINE_RETRIEVER_CONFIG = RetrieverConfig(
    enable_query_expansion=False,
    enable_metadata_boost=False,
    enable_section_boost=False,
    enable_evidence_adjustment=False,
    enable_topic_adjustment=False,
    enable_diversity_penalty=False,
    keyword_weight=1.0,
    vector_weight=1.0,
)


def coerce_retriever_config(value: RetrieverConfig | Mapping[str, Any] | None) -> RetrieverConfig:
    if value is None:
        return DEFAULT_RETRIEVER_CONFIG
    if isinstance(value, RetrieverConfig):
        return value
    return RetrieverConfig.from_mapping(value)

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
    mode: RetrievalMode = "keyword",
    top_k: int = 10,
    paper_id: str | None = None,
    author: str | None = None,
    year: int | None = None,
    section: str | None = None,
    provider: str = "auto",
    index_path: Path | None = None,
    include_text: bool = False,
    config: RetrieverConfig | Mapping[str, Any] | None = None,
    scope: RetrievalScope = "public",
) -> dict[str, Any]:
    resolved_config = coerce_retriever_config(config)
    warnings: list[str] = []
    filters = SearchFilters(paper_id=paper_id, author=author, year=year, section=section)
    expanded_query, query_expansions = (
        expand_query(query) if resolved_config.enable_query_expansion else (query, [])
    )

    keyword_results: list[dict[str, Any]] = []
    vector_results: list[dict[str, Any]] = []
    vector_provider, vector_index_path, provider_warnings = resolve_vector_backend(
        session,
        mode=mode,
        provider=provider,
        index_path=index_path,
    )
    warnings.extend(provider_warnings)

    candidate_k = max(top_k * resolved_config.candidate_multiplier, top_k)
    if scope == "public":
        # Ranking indexes are frozen over the technical evaluation corpus.
        # Scan that bounded corpus before applying the independent publication
        # projection, otherwise high-ranked non-public rows can starve a valid
        # public top-k result. The current corpus is intentionally small (the
        # authoritative snapshot is hundreds, not millions, of chunks).
        candidate_k = max(candidate_k, len(eligible_chunks(session)))
    elif scope != "technical":
        raise ValueError(f"unknown retrieval scope: {scope}")

    if mode in {"keyword", "hybrid"}:
        raw_keyword = search_keyword(session, expanded_query, top_k=candidate_k, filters=filters)
        keyword_results = enrich_keyword_results(session, raw_keyword, filters=filters)
    if mode in {"feature_hashing", "dense", "hybrid"}:
        vector_results, vector_warnings = search_vector_store(
            session,
            expanded_query,
            top_k=candidate_k,
            provider_name=vector_provider,
            index_path=vector_index_path,
            paper_id=paper_id,
            author=author,
            year=year,
            section=section,
        )
        warnings.extend(vector_warnings)

    # Defense in depth for stale or externally supplied index files: remove
    # non-public records before any rank fusion or re-ranking occurs.
    if scope == "public":
        keyword_results = filter_public_results(session, keyword_results)
        vector_results = filter_public_results(session, vector_results)

    results = rank_retrieval_components(
        keyword_results,
        vector_results,
        mode=mode,
        top_k=top_k,
        query=expanded_query,
        vector_provider=vector_provider,
        include_text=include_text,
        config=resolved_config,
    )

    return {
        "query": query,
        "expanded_query": expanded_query,
        "query_expansions": query_expansions,
        "mode": mode,
        "result_count": len(results),
        "results": results,
        "warnings": sanitize_public_retrieval_warnings(warnings) if scope == "public" else warnings,
        "vector_provider": vector_provider if mode != "keyword" else None,
        "retrieval_strategy": "explicit_config_v1",
        "retriever_config": resolved_config.to_dict(),
        "retrieval_scope": scope,
    }


def filter_public_results(session: Session, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paper_ids = {str(result.get("paper_id") or "") for result in results}
    allowed = {
        paper.paper_id
        for paper_id in paper_ids
        if paper_id and (paper := session.get(Paper, paper_id)) is not None and is_public_content(session, paper)
    }
    return [result for result in results if str(result.get("paper_id") or "") in allowed]


def sanitize_public_retrieval_warnings(warnings: list[str]) -> list[str]:
    """Keep anonymous warnings useful without disclosing workstation paths."""

    safe_known = {
        "Complete learned-dense index unavailable; hybrid retrieval explicitly fell back to feature hashing.",
        "The feature-hashing index is unavailable; no vector results were returned.",
        "The learned-dense index is unavailable; no vector results were returned.",
        "The learned-dense provider is unavailable; no vector results were returned.",
    }
    sanitized: list[str] = []
    for warning in warnings:
        value = str(warning)
        if value in safe_known:
            replacement = value
        elif re.search(r"(?:^|\s)(?:/[^\s]+|[A-Za-z]:[\\/][^\s]+|\.\.?[/\\][^\s]+)", value):
            replacement = "A retrieval component is unavailable; local configuration details are not exposed."
        else:
            replacement = value
        if replacement not in sanitized:
            sanitized.append(replacement)
    return sanitized


def rank_retrieval_components(
    keyword_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    *,
    mode: RetrievalMode,
    top_k: int,
    query: str,
    vector_provider: str = FEATURE_HASHING_PROVIDER,
    include_text: bool = False,
    config: RetrieverConfig | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank already-retrieved components under one explicit configuration.

    The experiment runner uses this pure re-ranking boundary to reuse the same
    frozen candidate pools for weight searches, ablations, and sensitivity
    analysis. Runtime callers continue to use :func:`retrieve`.
    """

    resolved_config = coerce_retriever_config(config)
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    selection_k = (
        max(top_k * resolved_config.candidate_multiplier, top_k)
        if resolved_config.enable_topic_adjustment and has_strong_topical_constraint(query)
        else top_k
    )
    if mode == "keyword":
        results = [
            format_result(
                result,
                rank,
                keyword=result["score"],
                semantic=0.0,
                query=query,
                include_text=include_text,
                config=resolved_config,
            )
            for rank, result in enumerate(keyword_results[:selection_k], start=1)
        ]
    elif mode in {"feature_hashing", "dense"}:
        results = [
            format_result(
                result,
                rank,
                keyword=0.0,
                semantic=result["score"],
                vector_provider=vector_provider,
                query=query,
                include_text=include_text,
                config=resolved_config,
            )
            for rank, result in enumerate(vector_results[:selection_k], start=1)
        ]
    elif mode == "hybrid":
        results = combine_hybrid(
            keyword_results,
            vector_results,
            top_k=selection_k,
            query=query,
            vector_provider=vector_provider,
            include_text=include_text,
            config=resolved_config,
        )
    else:  # pragma: no cover - Literal protects typed callers; retained for runtime validation.
        raise ValueError(f"unknown retrieval mode: {mode}")
    if resolved_config.enable_topic_adjustment:
        results = apply_topical_constraints(results, query, top_k=top_k)
    else:
        results = results[:top_k]
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank
    return results


def resolve_vector_backend(
    session: Session,
    *,
    mode: RetrievalMode,
    provider: str,
    index_path: Path | None,
) -> tuple[str, Path | None, list[str]]:
    # Keyword retrieval does not use, and must not make readiness claims about,
    # either vector index.  Resolve it before the provider auto-selection path
    # so a missing dense index cannot influence a lexical-only request.
    if mode == "keyword":
        return FEATURE_HASHING_PROVIDER, None, []
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
    config: RetrieverConfig | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    resolved_config = coerce_retriever_config(config)
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
        base_score = (
            entry["keyword"] * resolved_config.keyword_weight
            + entry["semantic"] * resolved_config.vector_weight
        )
        entry["metadata"] = (
            metadata_score(base, query) * resolved_config.metadata_scale
            if resolved_config.enable_metadata_boost
            else 0.0
        )
        entry["section_boost"] = (
            section_boost(str(base.get("section") or ""), query) * resolved_config.section_scale
            if resolved_config.enable_section_boost
            else 0.0
        )
        entry["evidence_quality"] = (
            evidence_quality_score(base) * resolved_config.evidence_scale
            if resolved_config.enable_evidence_adjustment
            else 0.0
        )
        entry["topical_alignment"] = (
            topical_alignment_score(base, query) * resolved_config.topic_scale
            if resolved_config.enable_topic_adjustment
            else 0.0
        )
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
    diversified = diversify_ranked_entries(
        ranked,
        top_k=top_k,
        enabled=resolved_config.enable_diversity_penalty,
        scale=resolved_config.diversity_scale,
    )
    return [
        format_result(
            entry["base"],
            rank,
            keyword=entry["keyword"],
            semantic=entry["semantic"],
            vector_provider=vector_provider,
            metadata=entry["metadata"],
            section=entry["section_boost"],
            evidence=entry["evidence_quality"],
            topic=entry["topical_alignment"],
            diversity=entry["diversity_penalty"],
            combined_override=entry["diversified_score"],
            query=query,
            include_text=include_text,
            config=resolved_config,
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
    evidence: float | None = None,
    topic: float | None = None,
    diversity: float = 0.0,
    combined_override: float | None = None,
    include_text: bool = False,
    config: RetrieverConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_config = coerce_retriever_config(config)
    metadata_score_value = metadata if metadata is not None else (
        metadata_score(result, query) * resolved_config.metadata_scale
        if resolved_config.enable_metadata_boost
        else 0.0
    )
    section_boost_value = section if section is not None else (
        section_boost(str(result.get("section") or ""), query) * resolved_config.section_scale
        if resolved_config.enable_section_boost
        else 0.0
    )
    evidence_quality_value = evidence if evidence is not None else (
        evidence_quality_score(result) * resolved_config.evidence_scale
        if resolved_config.enable_evidence_adjustment
        else 0.0
    )
    topical_alignment_value = topic if topic is not None else (
        topical_alignment_score(result, query) * resolved_config.topic_scale
        if resolved_config.enable_topic_adjustment
        else 0.0
    )
    combined = (
        combined_override
        if combined_override is not None
        else min(
            1.0,
            max(
                0.0,
                keyword * resolved_config.keyword_weight
                + semantic * resolved_config.vector_weight
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
            "vector": round(semantic, 6),
            "vector_provider": vector_provider,
            "metadata": round(metadata_score_value, 6),
            "section_boost": round(section_boost_value, 6),
            "evidence_quality": round(evidence_quality_value, 6),
            "topical_alignment": round(topical_alignment_value, 6),
            "diversity_penalty": round(diversity, 6),
            "combined": round(combined, 6),
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
        if contains_phrase(lowered, phrase):
            for expansion in expansions:
                if not contains_phrase(lowered, expansion) and expansion not in additions:
                    additions.append(expansion)
    if not additions:
        return query, []
    return f"{query} {' '.join(additions)}", additions


def contains_phrase(text: str, phrase: str) -> bool:
    """Match controlled terms on token/phrase boundaries, never substrings."""

    tokens = re.findall(r"[a-zA-Z0-9]+", phrase.lower())
    if not tokens:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s-]+".join(re.escape(token) for token in tokens) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


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
    if query_has_rag_constraint(lowered_query):
        has_rag_signal = has_rag_text(text)
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
    return query_has_rag_constraint(query)


def query_has_rag_constraint(query: str) -> bool:
    return contains_phrase(query, "rag") or contains_phrase(query, "retrieval augmented generation")


def has_rag_text(text: str) -> bool:
    return contains_phrase(text, "rag") or contains_phrase(text, "retrieval augmented")


def has_rag_signal(result: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(result.get("paper_title") or ""),
            str(result.get("snippet") or ""),
            str(result.get("text") or "")[:1200],
        ]
    ).lower()
    return has_rag_text(text)


def diversify_ranked_entries(
    entries: list[dict[str, Any]],
    *,
    top_k: int,
    enabled: bool = True,
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    remaining = [dict(entry) for entry in entries]
    while remaining and len(selected) < top_k:
        best_index = 0
        best_score = -1.0
        for index, entry in enumerate(remaining):
            penalty = diversity_penalty(entry, selected) * scale if enabled else 0.0
            score = max(0.0, float(entry["base_combined"]) - penalty)
            if score > best_score:
                best_score = score
                best_index = index
        picked = remaining.pop(best_index)
        picked["diversity_penalty"] = round(
            max(0.0, float(picked["base_combined"]) - best_score), 6
        )
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
    search.add_argument("--mode", choices=["keyword", "feature_hashing", "dense", "hybrid"], default="keyword")
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
