from __future__ import annotations

import argparse
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, desc, func, select

from app.db import create_db_and_tables, engine
from app.indexing.embedder import eligible_chunks
from app.indexing.retriever import RetrievalScope, retrieve
from app.intelligence.rag_answerer import assess_answerability
from app.intelligence.recommendation_verifier import verify_recommendations
from app.intelligence.paper_artifact_generator import strip_nested_correction_evidence
from app.models import Chunk, Paper, ThesisRecommendation
from app.runtime_provenance import build_runtime_provenance

RetrievalMode = Literal["keyword", "feature_hashing", "dense", "hybrid"]
GroundingStatus = Literal["grounded", "partial", "unsupported"]
Difficulty = Literal["easy", "medium", "hard"]

DEFAULT_PROVIDER = "offline_deterministic"
DEFAULT_MODEL = "template-recommender-v1"

# These weights are hand-authored heuristics. They have not been optimized on
# student outcomes or supervisor decisions. The recommendation proxy evaluator
# records local sensitivity around this exact configuration.
SCORE_WEIGHTS = {
    "retrieval_relevance": 0.30,
    "interest_topic_match": 0.20,
    "skill_match": 0.15,
    "data_feasibility": 0.10,
    "timeline_feasibility": 0.10,
    "difficulty_match": 0.10,
    "evidence_strength": 0.05,
}

FUTURE_WORK_TERMS = (
    "limitation",
    "limitations",
    "future work",
    "future research",
    "future studies",
    "further research",
    "we believe",
    "we recommend",
    "we propose",
    "could be extended",
    "remains to be",
    "improve",
    "improvement",
    "larger dataset",
    "larger data set",
)

EXPLICIT_GAP_TERMS = ("limitation", "limitations", "future work", "future research")
NEGATED_GAP_RE = re.compile(
    r"\b(?:no|not|without)\s+(?:\w+[\s,;:-]+){0,4}"
    r"(?:limitation|limitations|future work|future research|further research|recommendation|recommendations)\b"
    r"|\b(?:do|does|did)\s+not\s+(?:\w+[\s,;:-]+){0,4}"
    r"(?:limit|recommend|propose|suggest|identify)\b"
)

STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "based",
    "but",
    "can",
    "data",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "may",
    "not",
    "paper",
    "papers",
    "project",
    "research",
    "student",
    "that",
    "the",
    "their",
    "this",
    "with",
}


class ExtensionFinderRequest(BaseModel):
    interests: str = Field(min_length=1, max_length=2_000)
    skills: list[str] = Field(default_factory=list, max_length=50)
    available_time: Literal["2 weeks", "1 month", "semester"] = "semester"
    project_type: Literal[
        "software prototype",
        "data analysis",
        "ML experiment",
        "literature/systematic review support",
        "dashboard/visualization",
        "other",
    ] = "software prototype"
    data_constraints: str = Field(default="prefer public or synthetic data", max_length=1_000)
    preferred_difficulty: Difficulty = "medium"
    preferred_topics: list[str] = Field(default_factory=list, max_length=50)
    avoid_topics: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=5, ge=1, le=10)
    retrieval_mode: RetrievalMode = "keyword"
    provider: Literal["auto", "offline", "offline_deterministic"] = "auto"

    @field_validator("interests")
    @classmethod
    def interests_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("interests must not be empty")
        return value.strip()

    @field_validator("skills", "preferred_topics", "avoid_topics")
    @classmethod
    def remove_blank_list_items(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value and value.strip()]
        if any(len(value) > 200 for value in normalized):
            raise ValueError("profile list items may not exceed 200 characters")
        return normalized

    @field_validator("data_constraints")
    @classmethod
    def normalize_constraints(cls, value: str) -> str:
        return value.strip() or "unknown"


class ExtensionFinderResponse(BaseModel):
    recommendation_id: str
    request: dict[str, Any]
    grounding_status: GroundingStatus
    recommendations: list[dict[str, Any]]
    warnings: list[str]
    provider: str
    model: str
    retrieval_mode: RetrievalMode
    top_k: int
    runtime_provenance: dict[str, Any]
    created_at: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def recommend_extensions(
    session: Session,
    request: ExtensionFinderRequest,
    *,
    persist: bool = False,
    score_weights: Mapping[str, float] | None = None,
    retrieval_response: Mapping[str, Any] | None = None,
    retrieval_scope: RetrievalScope = "public",
) -> dict[str, Any]:
    created_at = utc_now()
    warnings: list[str] = []
    provider, model, provider_warnings = resolve_provider(request.provider)
    warnings.extend(provider_warnings)

    query = build_retrieval_query(request)
    retrieval = dict(retrieval_response) if retrieval_response is not None else retrieve(
        session,
        query,
        mode=request.retrieval_mode,
        top_k=max(request.top_k * 6, request.top_k),
        scope=retrieval_scope,
    )
    warnings.extend(retrieval.get("warnings", []))
    retrieved_results = retrieval.get("results", [])
    answerability = assess_answerability(query, retrieved_results, paper_id=None)
    if not retrieved_results or not answerability["answerable"]:
        response = {
            "recommendation_id": str(uuid.uuid4()),
            "request": request.model_dump(),
            "grounding_status": "unsupported",
            "recommendations": [],
            "warnings": dedupe_preserve_order(
                warnings
                + list(answerability.get("warnings", []))
                + ["No indexed TTLAB chunks defensibly matched the student profile."]
            ),
            "provider": provider,
            "model": model,
            "retrieval_mode": request.retrieval_mode,
            "top_k": request.top_k,
            "retrieval_scope": retrieval_scope,
            "answerability": answerability,
            "created_at": created_at.isoformat(),
        }
        response["runtime_provenance"] = build_runtime_provenance(
            session,
            record_type="thesis_recommendation",
            generation_config={
                "request": request.model_dump(),
                "score_weights": validated_score_weights(score_weights),
                "answerability_reason": answerability.get("reason"),
            },
            provider=provider,
            model=model,
            generated_at=created_at,
            retrieval_mode=request.retrieval_mode,
            source_chunk_ids=[
                str(result.get("chunk_id") or "") for result in retrieved_results
            ],
            retrieval_metadata={
                "retrieval_scope": retrieval_scope,
                "retrieval_strategy": retrieval.get("retrieval_strategy"),
                "retriever_config": retrieval.get("retriever_config", {}),
                "vector_provider": retrieval.get("vector_provider"),
            },
            corpus_scope=retrieval_scope,
        )
        if persist:
            store_recommendation(session, response, request)
        return response

    relevant_ids = set(answerability["relevant_chunk_ids"])
    retrieved_results = [
        result for result in retrieved_results if str(result.get("chunk_id") or "") in relevant_ids
    ]
    groups = group_results_by_paper(retrieved_results)
    scored_candidates = score_candidate_papers(groups, request, score_weights=score_weights)
    recommendations: list[dict[str, Any]] = []
    retrieved_chunks_by_id = {result["chunk_id"]: result for result in retrieved_results}

    for rank, candidate in enumerate(scored_candidates[: request.top_k], start=1):
        recommendation = build_offline_recommendation(
            candidate,
            rank=rank,
            request=request,
            all_candidates=scored_candidates,
        )
        recommendations.append(recommendation)

    verification = verify_recommendations(
        recommendations,
        retrieved_chunks_by_id,
        available_time=request.available_time,
    )
    response = {
        "recommendation_id": str(uuid.uuid4()),
        "request": request.model_dump(),
        "grounding_status": verification["grounding_status"],
        "recommendations": recommendations,
        "warnings": dedupe_preserve_order(warnings + verification["warnings"]),
        "provider": provider,
        "model": model,
        "retrieval_mode": request.retrieval_mode,
        "top_k": request.top_k,
        "retrieval_scope": retrieval_scope,
        "answerability": answerability,
        "created_at": created_at.isoformat(),
    }
    response["runtime_provenance"] = build_runtime_provenance(
        session,
        record_type="thesis_recommendation",
        generation_config={
            "request": request.model_dump(),
            "score_weights": validated_score_weights(score_weights),
            "verification_contract": "structural_support_unverified_v1",
        },
        provider=provider,
        model=model,
        generated_at=created_at,
        retrieval_mode=request.retrieval_mode,
        source_chunk_ids=[str(result.get("chunk_id") or "") for result in retrieved_results],
        retrieval_metadata={
            "retrieval_scope": retrieval_scope,
            "retrieval_strategy": retrieval.get("retrieval_strategy"),
            "retriever_config": retrieval.get("retriever_config", {}),
            "vector_provider": retrieval.get("vector_provider"),
        },
        corpus_scope=retrieval_scope,
    )
    if persist:
        store_recommendation(session, response, request)
    return response


def resolve_provider(provider_name: str) -> tuple[str, str, list[str]]:
    normalized = (provider_name or "auto").strip().lower()
    if normalized in {"auto", "offline", "offline_deterministic"}:
        return DEFAULT_PROVIDER, DEFAULT_MODEL, []
    return (
        DEFAULT_PROVIDER,
        DEFAULT_MODEL,
        [f"Provider '{provider_name}' is not implemented for Phase 5; used offline deterministic recommendations."],
    )


def build_retrieval_query(request: ExtensionFinderRequest) -> str:
    # Retrieval is intentionally topic-focused. Project-type, time, and data
    # constraints belong in reranking; generic "future work" terms previously
    # dominated short profile queries and produced off-topic candidate pools.
    query_parts = [
        request.interests,
        " ".join(request.preferred_topics),
    ]
    return " ".join(part for part in query_parts if part).strip()


def group_results_by_paper(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        paper_id = result["paper_id"]
        group = groups.setdefault(
            paper_id,
            {
                "paper_id": paper_id,
                "paper_title": result.get("paper_title") or "",
                "authors": result.get("authors") or [],
                "year": result.get("year"),
                "chunks": [],
                "source": result.get("source", {}),
                "best_score": 0.0,
            },
        )
        group["chunks"].append(result)
        group["best_score"] = max(group["best_score"], float(result.get("scores", {}).get("combined") or 0.0))
    return groups


def evidence_only_baseline(
    session: Session,
    request: ExtensionFinderRequest,
    *,
    retrieval_response: Mapping[str, Any] | None = None,
    retrieval_scope: RetrievalScope = "public",
) -> dict[str, Any]:
    """Return ranked papers and passages without generating advisory text.

    The baseline deliberately uses the same query, retrieval mode, result pool,
    and paper grouping as the full finder. Its paper ordering uses only the best
    retrieval score, so the experiment isolates the full finder's hand-authored
    profile reranking and template generation.
    """

    query = build_retrieval_query(request)
    retrieval = dict(retrieval_response) if retrieval_response is not None else retrieve(
        session,
        query,
        mode=request.retrieval_mode,
        top_k=max(request.top_k * 6, request.top_k),
        scope=retrieval_scope,
    )
    groups = group_results_by_paper(retrieval.get("results", []))
    ranked_groups = sorted(
        groups.values(),
        key=lambda item: (
            float(item.get("best_score") or 0.0),
            str(item.get("paper_title") or ""),
        ),
        reverse=True,
    )
    papers: list[dict[str, Any]] = []
    for rank, group in enumerate(ranked_groups[: request.top_k], start=1):
        papers.append(
            {
                "rank": rank,
                "paper_id": group["paper_id"],
                "paper_title": group["paper_title"],
                "authors": group["authors"],
                "year": group["year"],
                "retrieval_score": round(float(group.get("best_score") or 0.0), 6),
                "passages": [citation_from_result(result) for result in group["chunks"][:3]],
            }
        )
    return {
        "output_mode": "evidence_only",
        "query": query,
        "expanded_query": retrieval.get("expanded_query"),
        "retrieval_mode": request.retrieval_mode,
        "vector_provider": retrieval.get("vector_provider"),
        "top_k": request.top_k,
        "papers": papers,
        "warnings": retrieval.get("warnings", []),
        "disclaimer": (
            "Evidence-only retrieval does not propose an extension, estimate feasibility, "
            "claim novelty, or assign a supervisor."
        ),
    }


def score_candidate_papers(
    groups: dict[str, dict[str, Any]],
    request: ExtensionFinderRequest,
    *,
    score_weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    weights = validated_score_weights(score_weights)
    profile_terms = profile_tokens(request)
    scored: list[dict[str, Any]] = []
    for group in groups.values():
        chunks = group["chunks"]
        text_blob = " ".join(
            [group.get("paper_title") or ""]
            + [clean_markup(str(chunk.get("snippet") or "")) for chunk in chunks[:4]]
        )
        text_terms = set(tokenize(text_blob))
        avoid_penalty = 0.2 if matches_avoid_topic(text_blob, request.avoid_topics) else 0.0
        evidence_profile = analyze_candidate_evidence(group, text_blob)
        required_skills = infer_required_skills(request.project_type, text_blob)
        skill_match, skills_gap = calculate_skill_fit(request.skills, required_skills)
        component_scores = {
            "retrieval_relevance": max(float(group.get("best_score") or 0.0), max_result_score(chunks)),
            "interest_topic_match": lexical_overlap(profile_terms, text_terms),
            "skill_match": skill_match,
            "data_feasibility": data_feasibility_score(evidence_profile["data_availability"]["status"]),
            # The source rarely supports a schedule estimate. Retain a neutral
            # score rather than deriving feasibility from the requested time.
            "timeline_feasibility": 0.5,
            "difficulty_match": difficulty_match_score(request.preferred_difficulty, evidence_profile["difficulty"]["value"]),
            "evidence_strength": min(len(chunks) / 3.0, 1.0),
        }
        weighted_score = sum(component_scores[name] * weights[name] for name in weights) - avoid_penalty
        scored.append(
            {
                **group,
                "required_skills": required_skills,
                "skills_gap": skills_gap,
                "component_scores": {name: round(score, 4) for name, score in component_scores.items()},
                "fit_score": round(max(weighted_score, 0.0), 4),
                "difficulty": evidence_profile["difficulty"]["value"],
                "risk_level": infer_risk_level(evidence_profile, skills_gap),
                "data_availability": evidence_profile["data_availability"]["status"],
                "implementation_time": "unknown",
                "evidence_profile": evidence_profile,
            }
        )
    return sorted(scored, key=lambda item: (item["fit_score"], item["best_score"], item["paper_title"]), reverse=True)


def validated_score_weights(score_weights: Mapping[str, float] | None = None) -> dict[str, float]:
    """Validate and normalize an evaluation-only recommendation weight set."""

    weights = dict(SCORE_WEIGHTS if score_weights is None else score_weights)
    if set(weights) != set(SCORE_WEIGHTS):
        missing = sorted(set(SCORE_WEIGHTS) - set(weights))
        extra = sorted(set(weights) - set(SCORE_WEIGHTS))
        raise ValueError(f"score weight keys must match defaults; missing={missing} extra={extra}")
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0
        for value in weights.values()
    ):
        raise ValueError("score weights must be non-negative finite numbers")
    total = float(sum(weights.values()))
    if total <= 0:
        raise ValueError("at least one score weight must be positive")
    return {name: float(value) / total for name, value in weights.items()}


def build_offline_recommendation(
    candidate: dict[str, Any],
    *,
    rank: int,
    request: ExtensionFinderRequest,
    all_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    chunks = candidate["chunks"][:3]
    citations = [citation_from_result(result) for result in chunks]
    source_supported_facts = [fact_from_result(result) for result in chunks[:2]]
    focus_sentence = source_supported_facts[0]["claim"] if source_supported_facts else "No source-cited focus sentence was retrieved."
    gap = identify_gap(chunks)
    primary_interest = first_profile_phrase(request)
    extension_title = build_extension_title(candidate["paper_title"], primary_interest, request.project_type)
    required_skills = candidate["required_skills"]
    related_papers = build_related_papers(candidate, all_candidates)
    warnings = build_recommendation_warnings(candidate, gap, request)

    return {
        "rank": rank,
        "paper_id": candidate["paper_id"],
        "paper_title": candidate["paper_title"],
        "authors": candidate["authors"],
        "year": candidate["year"],
        "fit_score": candidate["fit_score"],
        "score_breakdown": candidate["component_scores"],
        "paper_focus": (
            f"{candidate['paper_title']} is represented in the retrieved chunks by this source-cited, "
            f"structurally unverified focus: {focus_sentence}"
        ),
        "source_supported_facts": source_supported_facts,
        "identified_gap": gap,
        "extension_title": extension_title,
        "extension_summary": build_extension_summary(extension_title, request, gap),
        "why_it_fits_student": build_fit_reason(candidate, request),
        "mvp_scope": build_mvp_scope(request, candidate),
        "mvp_scope_basis": {
            "classification": "system_suggestion",
            "source_chunk_ids": candidate["evidence_profile"]["source_chunk_ids"],
        },
        "stretch_goals": build_stretch_goals(request),
        "required_skills": required_skills,
        "skills_gap": candidate["skills_gap"],
        "data_required": build_data_required(request, candidate),
        "data_availability": candidate["data_availability"],
        "data_availability_evidence": candidate["evidence_profile"]["data_availability"],
        "evaluation_plan": build_evaluation_plan(request, candidate),
        "evaluation_plan_basis": {
            "classification": "system_suggestion",
            "source_chunk_ids": candidate["evidence_profile"]["evaluation"]["source_chunk_ids"],
        },
        "difficulty": candidate["difficulty"],
        "difficulty_basis": candidate["evidence_profile"]["difficulty"],
        "risk_level": candidate["risk_level"],
        "risk_basis": "system_estimate_from_source_evidence_and_reported_skill_gaps",
        "implementation_time": candidate["implementation_time"],
        "implementation_time_basis": {
            "classification": "unknown",
            "reason": "Retrieved paper evidence does not establish student implementation duration; confirm scope with a supervisor.",
        },
        "profile_constraints": {
            "classification": "student_supplied_preferences_not_paper_facts",
            "available_time": request.available_time,
            "data_constraints": request.data_constraints,
            "preferred_difficulty": request.preferred_difficulty,
        },
        "related_papers": related_papers,
        "potential_researcher_fit": [
            {
                "name": author,
                "reason": "Author of the source paper; not verified as a supervisor.",
            }
            for author in candidate["authors"][:3]
        ],
        "citations": citations,
        "warnings": warnings,
    }


def citation_from_result(result: dict[str, Any]) -> dict[str, Any]:
    source = result.get("source") or {}
    return {
        "paper_id": result["paper_id"],
        "title": result.get("paper_title") or "",
        "chunk_id": result["chunk_id"],
        "section": result.get("section"),
        "page_start": result.get("page_start"),
        "page_end": result.get("page_end"),
        "snippet": clean_markup(str(result.get("snippet") or "")),
        "score": result.get("scores", {}).get("combined", 0.0),
        "source_url": source.get("post_url"),
        "pdf_url": source.get("pdf_url"),
    }


def fact_from_result(result: dict[str, Any]) -> dict[str, Any]:
    snippet = clean_markup(str(result.get("snippet") or ""))
    claim = first_sentence(snippet) or snippet[:220]
    return {
        "claim": claim,
        "chunk_id": result["chunk_id"],
        "page_start": result.get("page_start"),
        "page_end": result.get("page_end"),
        "snippet": snippet,
        "support_status": "support_unverified",
        "entailment_verified": False,
    }


def identify_gap(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    for result in chunks:
        section = str(result.get("section") or "").lower()
        if any(label in section for label in ("reference", "related work", "literature review", "background")):
            continue
        snippet = clean_markup(str(result.get("snippet") or ""))
        for sentence in split_sentences(snippet):
            lowered_sentence = sentence.lower()
            if not any(term in lowered_sentence for term in FUTURE_WORK_TERMS):
                continue
            if NEGATED_GAP_RE.search(lowered_sentence):
                continue
            strong_section = any(label in section for label in ("limitation", "future", "conclusion", "discussion"))
            authorial_actor = bool(
                re.search(r"\b(?:we|our|this (?:paper|study|work))\b", lowered_sentence)
            )
            source_phrase = any(term in lowered_sentence for term in EXPLICIT_GAP_TERMS)
            support_status = (
                "source_phrase_unverified"
                if source_phrase and strong_section and authorial_actor
                else "inferred_from_paper"
            )
            prefix = (
                "Retrieved authorial limitation/future-work phrase (source meaning unverified)"
                if support_status == "source_phrase_unverified"
                else "Inferred extension opening from retrieved paper evidence"
            )
            return {
                "text": f"{prefix}: {sentence}",
                "support_status": support_status,
                "source_chunk_ids": [result["chunk_id"]],
            }
    return {
        "text": "No explicit limitation or future-work statement was found in the retrieved chunks; the extension is inferred from the paper focus and student profile.",
        "support_status": "not_found",
        "source_chunk_ids": [],
    }


def build_extension_title(paper_title: str, primary_interest: str, project_type: str) -> str:
    title_stub = trim_words(paper_title, 8)
    if project_type == "dashboard/visualization":
        return f"Interactive {primary_interest} dashboard extending {title_stub}"
    if project_type == "ML experiment":
        return f"Evaluation experiment for {primary_interest} based on {title_stub}"
    if project_type == "data analysis":
        return f"Data analysis extension for {primary_interest} in {title_stub}"
    if project_type == "literature/systematic review support":
        return f"Review-support workflow for {primary_interest} building on {title_stub}"
    return f"{primary_interest} prototype extending {title_stub}"


def build_extension_summary(title: str, request: ExtensionFinderRequest, gap: dict[str, Any]) -> str:
    support = gap.get("support_status", "not_found").replace("_", " ")
    return (
        f"Suggested extension: build '{title}' as a {request.project_type}. "
        f"The paper evidence status for the gap is {support}; the extension idea itself is a student-project suggestion, not a verified claim from the paper."
    )


def build_fit_reason(candidate: dict[str, Any], request: ExtensionFinderRequest) -> str:
    matched_skills = sorted(
        {
            required
            for required in candidate["required_skills"]
            if skill_is_covered(required, request.skills)
        }
    )
    skill_text = ", ".join(matched_skills) if matched_skills else "the supplied skills do not directly cover the required skills yet"
    topic_text = ", ".join(request.preferred_topics) if request.preferred_topics else request.interests
    return (
        f"This paper ranked well for the student-supplied interests around {topic_text}. "
        f"A {request.project_type} is a system-suggested format, not something the paper claims is feasible. "
        f"Matching reported skills include {skill_text}; implementation time remains unknown pending scope review."
    )


def build_mvp_scope(request: ExtensionFinderRequest, candidate: dict[str, Any]) -> str:
    focus = candidate_focus(candidate)
    prefix = f"System-suggested MVP for {candidate['paper_title']}: "
    if request.project_type == "software prototype":
        return prefix + f"build one input path and one inspectable workflow centered on {focus}, with source-linked results."
    if request.project_type == "data analysis":
        return prefix + f"create one reproducible analysis of {focus}, then report candidate-specific assumptions, charts, and limitations."
    if request.project_type == "ML experiment":
        return prefix + f"reproduce one source-evidenced method or baseline related to {focus}, then run one bounded extension and error analysis."
    if request.project_type == "literature/systematic review support":
        return prefix + f"build a review aid whose extraction fields are derived from the paper's treatment of {focus}, with human verification."
    if request.project_type == "dashboard/visualization":
        return prefix + f"build a small dashboard around {focus}, with a curated input, filters, and two decision-relevant views."
    return prefix + f"define one narrow question about {focus}, build one minimal artifact, and evaluate it on a manually reviewed sample."


def build_stretch_goals(request: ExtensionFinderRequest) -> list[str]:
    if request.project_type == "software prototype":
        return [
            "Add a review workflow for outputs.",
            "Compare keyword, learned-dense, and feature-hashing retrieval quality.",
            "Package the prototype for a supervisor demo.",
        ]
    if request.project_type == "ML experiment":
        return ["Add ablation tests.", "Compare against a second baseline.", "Analyze failure cases by topic or data source."]
    if request.project_type == "dashboard/visualization":
        return ["Add topic filters.", "Add downloadable charts.", "Add a short public-facing interpretation panel."]
    return ["Expand the dataset.", "Add human review notes.", "Compare results across at least two methods."]


def build_data_required(request: ExtensionFinderRequest, candidate: dict[str, Any]) -> str:
    availability = candidate["data_availability"]
    if availability == "synthetic":
        return "The source explicitly supports synthetic data; a toy subset is a system-suggested MVP choice."
    if availability == "public":
        return "The retrieved paper evidence indicates public/open data; verify the cited source and license before selecting a small sample."
    if availability == "needs_supervisor":
        return "Likely needs supervisor guidance for domain data; start with a public or synthetic substitute if access is delayed."
    if availability == "private":
        return "Private or sensitive data may be required; scope the MVP around anonymized, synthetic, or public substitute data."
    return "Data availability is unknown from the retrieved chunks; the student's preference does not establish access. Verify with the supervisor before committing to scope."


def build_evaluation_plan(request: ExtensionFinderRequest, candidate: dict[str, Any]) -> str:
    profile = candidate["evidence_profile"]["evaluation"]
    metric_text = ", ".join(profile["metrics"]) if profile["metrics"] else "a task-specific baseline and manually reviewed failure cases"
    prefix = f"System-suggested evaluation for {candidate['paper_title']}: "
    if request.project_type == "software prototype":
        return prefix + f"run 5-10 candidate-specific tasks and assess {metric_text}, source correctness, and usability."
    if request.project_type == "data analysis":
        return prefix + f"check reproducibility and data quality, compare {metric_text}, and report sensitivity and failure cases."
    if request.project_type == "ML experiment":
        return prefix + f"compare one baseline and one extension using {metric_text}, then inspect failed cases."
    if request.project_type == "literature/systematic review support":
        return prefix + f"compare extracted fields with a hand-labeled set and track {metric_text} plus reviewer effort."
    if request.project_type == "dashboard/visualization":
        return prefix + f"verify chart values and test representative tasks, using {metric_text} and user-observed failure cases."
    return prefix + f"define a small benchmark before implementation, compare {metric_text}, and report limits."


def build_related_papers(candidate: dict[str, Any], all_candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    related: list[dict[str, str]] = []
    current_terms = set(tokenize(candidate.get("paper_title") or ""))
    for other in all_candidates:
        if other["paper_id"] == candidate["paper_id"]:
            continue
        other_terms = set(tokenize(other.get("paper_title") or ""))
        overlap = current_terms.intersection(other_terms)
        if overlap or len(related) < 2:
            related.append(
                {
                    "paper_id": other["paper_id"],
                    "title": other["paper_title"],
                    "reason": "Retrieved for overlapping student-profile terms; review citations before treating it as closely related.",
                }
            )
        if len(related) >= 2:
            break
    return related


def build_recommendation_warnings(
    candidate: dict[str, Any],
    gap: dict[str, Any],
    request: ExtensionFinderRequest,
) -> list[str]:
    warnings: list[str] = []
    if gap.get("support_status") != "source_phrase_unverified":
        warnings.append("No authorial future-work or limitation phrase was located for this recommendation.")
    else:
        warnings.append("A source phrase was located, but its meaning and entailment remain unverified.")
    if candidate["skills_gap"]:
        warnings.append("Some required skills are not in the student profile.")
    if candidate["data_availability"] == "unknown":
        warnings.append("Data availability is unknown and needs supervisor confirmation before scoping the project.")
    if candidate["difficulty"] == "unknown":
        warnings.append("Difficulty is unknown because the retrieved evidence does not support an estimate.")
    if candidate["implementation_time"] == "unknown":
        warnings.append("Implementation time is unknown and must not be inferred from the student's available time.")
    if request.available_time == "2 weeks" and candidate["difficulty"] == "hard":
        warnings.append("This appears too ambitious for a two-week project unless scope is reduced.")
    return warnings


def store_recommendation(
    session: Session,
    response: dict[str, Any],
    request: ExtensionFinderRequest,
) -> None:
    record = ThesisRecommendation(
        recommendation_id=response["recommendation_id"],
        request_json=response["request"],
        student_interests_json=sorted(profile_tokens(request)),
        student_skills_json=request.skills,
        available_time=request.available_time,
        project_type=request.project_type,
        data_constraints=request.data_constraints,
        preferred_difficulty=request.preferred_difficulty,
        recommendations_json=response["recommendations"],
        provider=response["provider"],
        model=response["model"],
        retrieval_mode=response["retrieval_mode"],
        top_k=response["top_k"],
        grounding_status=response["grounding_status"],
        warnings_json=response["warnings"],
        runtime_provenance_json=response.get("runtime_provenance", {}),
        created_at=datetime.fromisoformat(response["created_at"]),
    )
    session.add(record)
    session.commit()


def serialize_recommendation(record: ThesisRecommendation) -> dict[str, Any]:
    correction_blockers = recommendation_correction_blockers(record)
    correction_used = bool(record.corrected_recommendations_json)
    effective_available = record.review_status == "approved" and not correction_blockers
    return {
        "recommendation_id": record.recommendation_id,
        "request": record.request_json,
        "grounding_status": record.grounding_status,
        "recommendations": record.recommendations_json,
        "warnings": record.warnings_json,
        "provider": record.provider,
        "model": record.model,
        "retrieval_mode": record.retrieval_mode,
        "top_k": record.top_k,
        "runtime_provenance": record.runtime_provenance_json,
        "review_status": record.review_status,
        "reviewer_notes": record.reviewer_notes,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "reviewed_by": record.reviewed_by,
        "corrected_recommendations_json": record.corrected_recommendations_json,
        "correction_grounding_status": record.correction_grounding_status,
        "correction_source_chunk_ids": record.correction_source_chunk_ids_json,
        "correction_citations": record.correction_citations_json,
        "correction_runtime_provenance": record.correction_runtime_provenance_json,
        "approval_blockers": correction_blockers,
        "effective_recommendations_json": (
            record.corrected_recommendations_json
            if effective_available and correction_used
            else {"items": record.recommendations_json} if effective_available else None
        ),
        "created_at": record.created_at.isoformat(),
    }


def canonicalize_recommendation_correction(payload: dict[str, Any]) -> dict[str, Any]:
    """Project a reviewer correction onto a citation-free recommendation shape."""

    stripped = strip_nested_correction_evidence(payload)
    items = stripped.get("items") if isinstance(stripped, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Recommendation correction requires a non-empty items list")
    canonical_items: list[dict[str, Any]] = []
    required_text = (
        "paper_id",
        "paper_title",
        "extension_title",
        "extension_summary",
        "mvp_scope",
        "evaluation_plan",
    )
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each corrected recommendation must be an object")
        for field_name in required_text:
            if not isinstance(item.get(field_name), str) or not item[field_name].strip():
                raise ValueError(f"Corrected recommendation requires non-empty {field_name}")
        difficulty = item.get("difficulty")
        risk_level = item.get("risk_level")
        if difficulty not in {"easy", "medium", "hard", "unknown"}:
            raise ValueError("Corrected recommendation difficulty is invalid")
        if risk_level not in {"low", "medium", "high"}:
            raise ValueError("Corrected recommendation risk_level is invalid")
        canonical_item: dict[str, Any] = {
            "paper_id": item["paper_id"].strip(),
            "paper_title": item["paper_title"].strip(),
            "extension_title": item["extension_title"].strip(),
            "extension_summary": item["extension_summary"].strip(),
            "mvp_scope": item["mvp_scope"].strip(),
            "stretch_goals": _recommendation_string_list(item.get("stretch_goals")),
            "required_skills": _recommendation_string_list(item.get("required_skills")),
            "skills_gap": _recommendation_string_list(item.get("skills_gap")),
            "data_required": str(item.get("data_required") or "Unknown; confirm before scoping.").strip(),
            "data_availability": str(item.get("data_availability") or "unknown").strip(),
            "evaluation_plan": item["evaluation_plan"].strip(),
            "difficulty": difficulty,
            "risk_level": risk_level,
            "implementation_time": str(item.get("implementation_time") or "unknown").strip(),
            "citations": [],
            "warnings": list(
                dict.fromkeys(
                    [
                        *_recommendation_string_list(item.get("warnings")),
                        "Reviewer-corrected recommendation; source evidence has not been reverified.",
                    ]
                )
            ),
        }
        if isinstance(item.get("rank"), int):
            canonical_item["rank"] = item["rank"]
        if isinstance(item.get("why_it_fits_student"), str) and item["why_it_fits_student"].strip():
            canonical_item["why_it_fits_student"] = item["why_it_fits_student"].strip()
        canonical_items.append(canonical_item)
    return {
        "items": canonical_items,
        "correction_notice": (
            "Reviewer-corrected recommendation content. Nested citations and source locators were removed because "
            "the correction has not been reverified against source chunks."
        ),
    }


def _recommendation_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip()))


def recommendation_correction_blockers(record: ThesisRecommendation) -> list[str]:
    correction = record.corrected_recommendations_json
    if not isinstance(correction, dict) or not correction:
        return []
    blockers: list[str] = []
    try:
        canonical = canonicalize_recommendation_correction(correction)
    except ValueError:
        blockers.append("correction_payload_invalid")
        return blockers
    if canonical != correction:
        blockers.append("correction_not_canonical_or_contains_unverified_evidence")
    if record.correction_source_chunk_ids_json or record.correction_citations_json:
        blockers.append("correction_evidence_not_reverified")
    if record.correction_grounding_status != "unsupported":
        blockers.append("correction_grounding_status_inconsistent")
    return blockers


def recommendation_diagnostics(session: Session, *, demo_preview: bool = False) -> dict[str, Any]:
    # This route is anonymous, so it reports only the public projection and
    # does not expose draft run counts or technical-corpus inventory.
    if demo_preview:
        technical_chunks = eligible_chunks(session)
        searchable_chunks = len(technical_chunks)
        searchable_papers = len({chunk.paper_id for chunk in technical_chunks})
    else:
        eligible_join = Chunk.paper_id == Paper.paper_id
        searchable_chunks = session.exec(
        select(func.count())
        .select_from(Chunk)
        .join(Paper, eligible_join)
        .where(Paper.corpus_eligibility_status == "eligible")
        .where(Paper.review_status == "approved")
        .where(Paper.publication_status == "published")
        .where(Paper.rights_status == "cleared")
        .where(Paper.public_access_level == "searchable")
        .where(Paper.extraction_review_status == "approved")
        .where(Paper.extraction_generation_id.is_not(None))
        .where(Paper.chunk_generation_id.is_not(None))
        .where(Paper.chunk_extraction_generation_id == Paper.extraction_generation_id)
        .where(Paper.public_index_generation_id == Paper.chunk_generation_id)
        .where(Chunk.extraction_generation_id == Paper.extraction_generation_id)
        ).one()
        searchable_papers = session.exec(
        select(func.count(func.distinct(Chunk.paper_id)))
        .select_from(Chunk)
        .join(Paper, eligible_join)
        .where(Paper.corpus_eligibility_status == "eligible")
        .where(Paper.review_status == "approved")
        .where(Paper.publication_status == "published")
        .where(Paper.rights_status == "cleared")
        .where(Paper.public_access_level == "searchable")
        .where(Paper.extraction_review_status == "approved")
        .where(Paper.extraction_generation_id.is_not(None))
        .where(Paper.chunk_generation_id.is_not(None))
        .where(Paper.chunk_extraction_generation_id == Paper.extraction_generation_id)
        .where(Paper.public_index_generation_id == Paper.chunk_generation_id)
        .where(Chunk.extraction_generation_id == Paper.extraction_generation_id)
        ).one()
    return {
        "total_recommendation_runs": None,
        "total_recommendations_generated": None,
        "grounded_runs": None,
        "partial_runs": None,
        "unsupported_runs": None,
        "history_counts_visibility": "protected_reviewer_only",
        "history_counts_observed": False,
        "searchable_chunks": searchable_chunks,
        "searchable_papers": searchable_papers,
        "raw_chunks": None,
        "raw_papers_with_chunks": None,
        "default_provider": DEFAULT_PROVIDER,
        "last_recommendation_timestamp": None,
        "scope": "technical_demo" if demo_preview else "public",
        "demo_preview": demo_preview,
        "corpus_access_mode": "unreviewed_local_demo_preview" if demo_preview else "approved_public_projection",
    }


def profile_tokens(request: ExtensionFinderRequest) -> set[str]:
    return set(tokenize(" ".join([request.interests, " ".join(request.preferred_topics), request.project_type])))


def infer_required_skills(project_type: str, text_blob: str) -> list[str]:
    base_by_type = {
        "software prototype": ["Python", "FastAPI", "React", "API design", "evaluation"],
        "data analysis": ["Python", "statistics", "data cleaning", "visualization"],
        "ML experiment": ["Python", "machine learning", "data preprocessing", "evaluation"],
        "literature/systematic review support": ["research methods", "literature review", "data extraction", "Python"],
        "dashboard/visualization": ["visualization", "React", "data cleaning", "UI design"],
        "other": ["Python", "research methods", "evaluation"],
    }
    skills = list(base_by_type.get(project_type, base_by_type["other"]))
    lowered = text_blob.lower()
    if any(term in lowered for term in ("rag", "retrieval", "llm", "language model")):
        skills.append("information retrieval")
    if any(term in lowered for term in ("machine learning", "deep learning", "neural", "classification")):
        skills.append("machine learning")
    if "optimization" in lowered:
        skills.append("optimization")
    if "network" in lowered:
        skills.append("network analysis")
    if any(term in lowered for term in ("agriculture", "climate", "traffic", "telecommunication")):
        skills.append("domain research")
    return dedupe_preserve_order(skills)


def calculate_skill_fit(student_skills: list[str], required_skills: list[str]) -> tuple[float, list[str]]:
    if not required_skills:
        return 1.0, []
    covered = [skill for skill in required_skills if skill_is_covered(skill, student_skills)]
    gaps = [skill for skill in required_skills if skill not in covered]
    return round(len(covered) / len(required_skills), 4), gaps


def skill_is_covered(required_skill: str, student_skills: list[str]) -> bool:
    required_tokens = set(tokenize(required_skill))
    if not required_tokens:
        return False
    student_blob = " ".join(student_skills).lower()
    student_tokens = set(tokenize(student_blob))
    if required_skill.lower() in student_blob:
        return True
    return bool(required_tokens.intersection(student_tokens))


def analyze_candidate_evidence(group: dict[str, Any], text_blob: str) -> dict[str, Any]:
    lowered = text_blob.lower()
    chunks = group.get("chunks", [])[:4]
    source_chunk_ids = [str(chunk.get("chunk_id") or "") for chunk in chunks if chunk.get("chunk_id")]
    public_terms = ("publicly available", "open dataset", "open data", "public dataset")
    private_terms = ("private dataset", "confidential", "proprietary", "restricted data")
    supervisor_terms = ("available upon request", "provided by", "institutional data", "permission")
    synthetic_terms = ("synthetic data", "simulated data", "simulation dataset")
    if any(term in lowered for term in private_terms):
        data_status = "private"
        matched_data_terms = [term for term in private_terms if term in lowered]
    elif any(term in lowered for term in supervisor_terms):
        data_status = "needs_supervisor"
        matched_data_terms = [term for term in supervisor_terms if term in lowered]
    elif any(term in lowered for term in public_terms):
        data_status = "public"
        matched_data_terms = [term for term in public_terms if term in lowered]
    elif any(term in lowered for term in synthetic_terms):
        data_status = "synthetic"
        matched_data_terms = [term for term in synthetic_terms if term in lowered]
    else:
        data_status = "unknown"
        matched_data_terms = []

    hard_terms = ("deep learning", "multi-agent", "mixed integer", "optimization", "large language model")
    medium_terms = ("machine learning", "classification", "neural network", "retrieval", "web application")
    matched_hard = [term for term in hard_terms if term in lowered]
    matched_medium = [term for term in medium_terms if term in lowered]
    if matched_hard:
        difficulty = "hard"
        difficulty_terms = matched_hard
    elif matched_medium:
        difficulty = "medium"
        difficulty_terms = matched_medium
    else:
        difficulty = "unknown"
        difficulty_terms = []

    metric_terms = (
        "accuracy", "precision", "recall", "f1", "latency", "throughput", "mean squared error",
        "root mean squared error", "user study", "benchmark", "baseline",
    )
    metrics = [term for term in metric_terms if term in lowered]

    def matching_source_ids(terms: list[str]) -> list[str]:
        if not terms:
            return []
        return [
            str(chunk["chunk_id"])
            for chunk in chunks
            if chunk.get("chunk_id")
            and any(
                term in " ".join(
                    [
                        str(chunk.get("section") or ""),
                        str(chunk.get("snippet") or ""),
                        str(chunk.get("text") or ""),
                    ]
                ).lower()
                for term in terms
            )
        ]

    data_source_ids = matching_source_ids(matched_data_terms)
    difficulty_source_ids = matching_source_ids([*matched_hard, *matched_medium])
    evaluation_source_ids = matching_source_ids(metrics)
    return {
        "source_chunk_ids": source_chunk_ids,
        "data_availability": {
            "status": data_status,
            "classification": "source_evidenced" if matched_data_terms else "unknown",
            "matched_terms": matched_data_terms,
            "source_chunk_ids": data_source_ids,
        },
        "difficulty": {
            "value": difficulty,
            "classification": "system_estimate_from_source_terms" if difficulty_terms else "unknown",
            "matched_terms": difficulty_terms,
            "source_chunk_ids": difficulty_source_ids,
        },
        "evaluation": {
            "classification": "source_terms_plus_system_suggestion" if metrics else "system_suggestion",
            "metrics": metrics,
            "source_chunk_ids": evaluation_source_ids,
        },
    }


def candidate_focus(candidate: dict[str, Any]) -> str:
    chunks = candidate.get("chunks", [])
    if chunks:
        sentence = first_sentence(clean_markup(str(chunks[0].get("snippet") or "")))
        if sentence:
            return trim_words(sentence, 18)
    return f"the source-evidenced focus of {candidate.get('paper_title') or 'the paper'}"


def data_feasibility_score(availability: str) -> float:
    return {
        "public": 1.0,
        "synthetic": 0.85,
        "needs_supervisor": 0.55,
        "unknown": 0.45,
        "private": 0.25,
    }.get(availability, 0.45)


def timeline_feasibility_score(available_time: str, project_type: str, difficulty: str) -> float:
    if available_time == "semester":
        return 1.0
    if available_time == "1 month":
        return 0.9 if difficulty in {"easy", "medium"} else 0.5
    if project_type in {"data analysis", "dashboard/visualization"} and difficulty == "easy":
        return 0.75
    return 0.4


def infer_implementation_time(available_time: str, preferred_difficulty: str) -> str:
    if available_time == "semester":
        return "semester"
    if available_time == "1 month":
        return "1 month"
    return "2 weeks" if preferred_difficulty == "easy" else "1 month"


def timeline_fits(available_time: str, implementation_time: str) -> bool:
    order = {"2 weeks": 0, "1 month": 1, "semester": 2}
    return order.get(implementation_time, 99) <= order.get(available_time, -1)


def difficulty_match_score(preferred: str, inferred: str) -> float:
    if preferred == inferred:
        return 1.0
    if {preferred, inferred} == {"easy", "medium"} or {preferred, inferred} == {"medium", "hard"}:
        return 0.65
    return 0.3


def infer_risk_level(evidence_profile: dict[str, Any], skills_gap: list[str]) -> Literal["low", "medium", "high"]:
    availability = evidence_profile["data_availability"]["status"]
    difficulty = evidence_profile["difficulty"]["value"]
    if availability in {"private", "unknown"} and difficulty == "hard":
        return "high"
    if availability == "private" or len(skills_gap) >= 4:
        return "high"
    if availability == "unknown" or skills_gap or difficulty in {"hard", "unknown"}:
        return "medium"
    # Implementation time is intentionally unknown until a human scopes the
    # recommendation, so even otherwise favorable evidence remains uncertain.
    return "medium"


def max_result_score(results: list[dict[str, Any]]) -> float:
    return max((float(result.get("scores", {}).get("combined") or 0.0) for result in results), default=0.0)


def lexical_overlap(profile_terms: set[str], text_terms: set[str]) -> float:
    if not profile_terms or not text_terms:
        return 0.0
    return round(len(profile_terms.intersection(text_terms)) / len(profile_terms), 4)


def matches_avoid_topic(text: str, avoid_topics: Sequence[str]) -> bool:
    """Match each avoid topic as a phrase/conjunction, not any shared token.

    Treating ``private datasets`` as the independent tokens ``private`` and
    ``datasets`` previously penalized every dataset paper, including the exact
    synthetic-data target. Multi-token avoid preferences now require all
    meaningful tokens to occur in the candidate evidence.
    """

    text_terms = set(tokenize(text))
    for topic in avoid_topics:
        topic_terms = set(tokenize(topic))
        if topic_terms and topic_terms.issubset(text_terms):
            return True
    return False


def first_profile_phrase(request: ExtensionFinderRequest) -> str:
    terms = [part.strip() for part in re.split(r"[,;/]", request.interests) if part.strip()]
    if terms:
        return trim_words(terms[0], 5).lower()
    return "research"


def tokenize(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 1]
    return [token for token in tokens if token not in STOPWORDS]


def clean_markup(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("[[", "").replace("]]", "")).strip()


def split_sentences(text: str) -> list[str]:
    cleaned = clean_markup(text)
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", cleaned) if part.strip()]


def first_sentence(text: str) -> str:
    sentences = split_sentences(text)
    return sentences[0] if sentences else ""


def sentence_containing_term(text: str, terms: tuple[str, ...]) -> str:
    for sentence in split_sentences(text):
        lowered = sentence.lower()
        if any(term in lowered for term in terms):
            return sentence
    return ""


def trim_words(text: str, max_words: int) -> str:
    words = clean_markup(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:") + "..."


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate citation-grounded thesis extension recommendations.")
    subparsers = parser.add_subparsers(dest="command")
    recommend = subparsers.add_parser("recommend")
    recommend.add_argument("--interests", required=True)
    recommend.add_argument("--skills", nargs="*", default=[])
    recommend.add_argument("--available-time", default="semester", choices=["2 weeks", "1 month", "semester"])
    recommend.add_argument("--project-type", default="software prototype")
    recommend.add_argument("--data-constraints", default="prefer public or synthetic data")
    recommend.add_argument("--preferred-difficulty", default="medium", choices=["easy", "medium", "hard"])
    recommend.add_argument("--preferred-topics", nargs="*", default=[])
    recommend.add_argument("--avoid-topics", nargs="*", default=[])
    recommend.add_argument("--top-k", type=int, default=5)
    recommend.add_argument("--mode", default="keyword", choices=["keyword", "feature_hashing", "dense", "hybrid"])
    recommend.add_argument("--provider", default="auto")
    recommend.add_argument("--scope", choices=["public", "technical"], default="public")
    recommend.add_argument(
        "--persist",
        action="store_true",
        help="Store the recommendation run and student profile in local history.",
    )
    return parser


def print_cli_response(response: dict[str, Any]) -> None:
    print(f"recommendation_id: {response['recommendation_id']}")
    print(f"grounding_status: {response['grounding_status']}")
    print(f"provider: {response['provider']} model: {response['model']}")
    for recommendation in response["recommendations"]:
        print("")
        print(f"{recommendation['rank']}. {recommendation['paper_title']} ({recommendation.get('year') or 'year needs review'})")
        print(f"   extension: {recommendation['extension_title']}")
        print(f"   why it fits: {recommendation['why_it_fits_student']}")
        print(f"   MVP: {recommendation['mvp_scope']}")
        print(f"   difficulty/risk/time: {recommendation['difficulty']} / {recommendation['risk_level']} / {recommendation['implementation_time']}")
        print(f"   evaluation: {recommendation['evaluation_plan']}")
        print("   citations:")
        for citation in recommendation["citations"]:
            print(
                f"   - {citation['title']} pages {citation['page_start'] or '?'}-{citation['page_end'] or '?'} "
                f"chunk_id={citation['chunk_id']}"
            )
        if recommendation["warnings"]:
            print("   warnings:")
            for warning in recommendation["warnings"]:
                print(f"   - {warning}")
    if response["warnings"]:
        print("")
        print("run warnings:")
        for warning in response["warnings"]:
            print(f"- {warning}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "recommend":
        build_parser().print_help()
        return
    create_db_and_tables()
    request = ExtensionFinderRequest(
        interests=args.interests,
        skills=args.skills,
        available_time=args.available_time,
        project_type=args.project_type,
        data_constraints=args.data_constraints,
        preferred_difficulty=args.preferred_difficulty,
        preferred_topics=args.preferred_topics,
        avoid_topics=args.avoid_topics,
        top_k=args.top_k,
        retrieval_mode=args.mode,
        provider=args.provider,
    )
    with Session(engine) as session:
        response = recommend_extensions(
            session,
            request,
            persist=args.persist,
            retrieval_scope=args.scope,
        )
    print_cli_response(response)


if __name__ == "__main__":
    main()
