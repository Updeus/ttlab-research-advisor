from __future__ import annotations

import argparse
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, desc, func, select

from app.db import create_db_and_tables, engine
from app.indexing.retriever import retrieve
from app.intelligence.recommendation_verifier import verify_recommendations
from app.models import Chunk, Paper, ThesisRecommendation

RetrievalMode = Literal["keyword", "semantic", "hybrid"]
GroundingStatus = Literal["grounded", "partial", "unsupported"]
Difficulty = Literal["easy", "medium", "hard"]

DEFAULT_PROVIDER = "offline_deterministic"
DEFAULT_MODEL = "template-recommender-v1"

# Scoring weights are intentionally simple and deterministic for the MVP.
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
    "challenge",
    "challenges",
    "improve",
    "improvement",
    "extend",
    "extension",
    "evaluation",
    "dataset",
    "data set",
)

EXPLICIT_GAP_TERMS = ("limitation", "limitations", "future work", "future research")

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
    interests: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    available_time: Literal["2 weeks", "1 month", "semester"] = "semester"
    project_type: Literal[
        "software prototype",
        "data analysis",
        "ML experiment",
        "literature/systematic review support",
        "dashboard/visualization",
        "other",
    ] = "software prototype"
    data_constraints: str = "prefer public or synthetic data"
    preferred_difficulty: Difficulty = "medium"
    preferred_topics: list[str] = Field(default_factory=list)
    avoid_topics: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=10)
    retrieval_mode: RetrievalMode = "hybrid"
    provider: str = "auto"

    @field_validator("interests")
    @classmethod
    def interests_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("interests must not be empty")
        return value.strip()

    @field_validator("skills", "preferred_topics", "avoid_topics")
    @classmethod
    def remove_blank_list_items(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]

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
    created_at: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def recommend_extensions(
    session: Session,
    request: ExtensionFinderRequest,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    created_at = utc_now()
    warnings: list[str] = []
    provider, model, provider_warnings = resolve_provider(request.provider)
    warnings.extend(provider_warnings)

    query = build_retrieval_query(request)
    retrieval = retrieve(
        session,
        query,
        mode=request.retrieval_mode,
        top_k=max(request.top_k * 6, request.top_k),
    )
    warnings.extend(retrieval.get("warnings", []))
    retrieved_results = retrieval.get("results", [])
    if not retrieved_results:
        response = {
            "recommendation_id": str(uuid.uuid4()),
            "request": request.model_dump(),
            "grounding_status": "unsupported",
            "recommendations": [],
            "warnings": warnings + ["No indexed TTLAB chunks matched the student profile."],
            "provider": provider,
            "model": model,
            "retrieval_mode": request.retrieval_mode,
            "top_k": request.top_k,
            "created_at": created_at.isoformat(),
        }
        if persist:
            store_recommendation(session, response, request)
        return response

    groups = group_results_by_paper(retrieved_results)
    scored_candidates = score_candidate_papers(groups, request)
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
        "created_at": created_at.isoformat(),
    }
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
    query_parts = [
        request.interests,
        " ".join(request.preferred_topics),
        request.project_type,
        request.data_constraints,
        "future work limitations evaluation dataset challenge extension",
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


def score_candidate_papers(
    groups: dict[str, dict[str, Any]],
    request: ExtensionFinderRequest,
) -> list[dict[str, Any]]:
    profile_terms = profile_tokens(request)
    avoid_terms = set(tokenize(" ".join(request.avoid_topics)))
    scored: list[dict[str, Any]] = []
    for group in groups.values():
        chunks = group["chunks"]
        text_blob = " ".join(
            [group.get("paper_title") or ""]
            + [clean_markup(str(chunk.get("snippet") or "")) for chunk in chunks[:4]]
        )
        text_terms = set(tokenize(text_blob))
        avoid_penalty = 0.2 if avoid_terms and text_terms.intersection(avoid_terms) else 0.0
        required_skills = infer_required_skills(request.project_type, text_blob)
        skill_match, skills_gap = calculate_skill_fit(request.skills, required_skills)
        component_scores = {
            "retrieval_relevance": max(float(group.get("best_score") or 0.0), max_result_score(chunks)),
            "interest_topic_match": lexical_overlap(profile_terms, text_terms),
            "skill_match": skill_match,
            "data_feasibility": data_feasibility_score(request.data_constraints, text_blob),
            "timeline_feasibility": timeline_feasibility_score(request.available_time, request.project_type, request.preferred_difficulty),
            "difficulty_match": difficulty_match_score(request.preferred_difficulty, infer_difficulty(request, text_blob)),
            "evidence_strength": min(len(chunks) / 3.0, 1.0),
        }
        weighted_score = sum(component_scores[name] * SCORE_WEIGHTS[name] for name in SCORE_WEIGHTS) - avoid_penalty
        scored.append(
            {
                **group,
                "required_skills": required_skills,
                "skills_gap": skills_gap,
                "component_scores": {name: round(score, 4) for name, score in component_scores.items()},
                "fit_score": round(max(weighted_score, 0.0), 4),
                "difficulty": infer_difficulty(request, text_blob),
                "risk_level": infer_risk_level(request, skills_gap, text_blob),
                "data_availability": infer_data_availability(request.data_constraints, text_blob),
                "implementation_time": infer_implementation_time(request.available_time, request.preferred_difficulty),
            }
        )
    return sorted(scored, key=lambda item: (item["fit_score"], item["best_score"], item["paper_title"]), reverse=True)


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
    focus_sentence = source_supported_facts[0]["claim"] if source_supported_facts else "No source-supported focus sentence was retrieved."
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
        "paper_focus": f"{candidate['paper_title']} is represented in the retrieved chunks by this source-supported focus: {focus_sentence}",
        "source_supported_facts": source_supported_facts,
        "identified_gap": gap,
        "extension_title": extension_title,
        "extension_summary": build_extension_summary(extension_title, request, gap),
        "why_it_fits_student": build_fit_reason(candidate, request),
        "mvp_scope": build_mvp_scope(request, candidate),
        "stretch_goals": build_stretch_goals(request),
        "required_skills": required_skills,
        "skills_gap": candidate["skills_gap"],
        "data_required": build_data_required(request, candidate),
        "data_availability": candidate["data_availability"],
        "evaluation_plan": build_evaluation_plan(request),
        "difficulty": candidate["difficulty"],
        "risk_level": candidate["risk_level"],
        "implementation_time": candidate["implementation_time"],
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
    }


def identify_gap(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    fallback_chunk_id = chunks[0]["chunk_id"] if chunks else None
    for result in chunks:
        snippet = clean_markup(str(result.get("snippet") or ""))
        lowered = snippet.lower()
        if not any(term in lowered for term in FUTURE_WORK_TERMS):
            continue
        sentence = sentence_containing_term(snippet, FUTURE_WORK_TERMS) or first_sentence(snippet) or snippet[:220]
        support_status = "explicit_in_paper" if any(term in lowered for term in EXPLICIT_GAP_TERMS) else "inferred_from_paper"
        prefix = "Retrieved limitation/future-work evidence" if support_status == "explicit_in_paper" else "Retrieved evidence that suggests an extension opening"
        return {
            "text": f"{prefix}: {sentence}",
            "support_status": support_status,
            "source_chunk_ids": [result["chunk_id"]],
        }
    return {
        "text": "No explicit limitation or future-work statement was found in the retrieved chunks; the extension is inferred from the paper focus and student profile.",
        "support_status": "not_found",
        "source_chunk_ids": [fallback_chunk_id] if fallback_chunk_id else [],
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
        f"This paper ranked well for interests around {topic_text}. "
        f"It also fits the requested {request.project_type} format and a {request.available_time} timeline; matching skills include {skill_text}."
    )


def build_mvp_scope(request: ExtensionFinderRequest, candidate: dict[str, Any]) -> str:
    if request.project_type == "software prototype":
        return "Build a small working prototype with one ingestion/input path, one analysis or recommendation workflow, and a cited results view."
    if request.project_type == "data analysis":
        return "Create a reproducible notebook or script that collects a small dataset, performs the core analysis, and reports interpretable charts plus limitations."
    if request.project_type == "ML experiment":
        return "Run a baseline model and one extension experiment, compare against a simple metric, and document errors with cited paper motivation."
    if request.project_type == "literature/systematic review support":
        return "Build a structured review aid that extracts candidate papers, labels evidence fields, and exports a review table for human checking."
    if request.project_type == "dashboard/visualization":
        return "Build a dashboard with a small curated dataset, filters, and at least two visuals that answer a concrete research or public-facing question."
    return "Define one narrow research question, build a minimal artifact, and evaluate it against a small manually reviewed benchmark."


def build_stretch_goals(request: ExtensionFinderRequest) -> list[str]:
    if request.project_type == "software prototype":
        return ["Add a review workflow for outputs.", "Compare keyword and semantic retrieval quality.", "Package the prototype for a supervisor demo."]
    if request.project_type == "ML experiment":
        return ["Add ablation tests.", "Compare against a second baseline.", "Analyze failure cases by topic or data source."]
    if request.project_type == "dashboard/visualization":
        return ["Add topic filters.", "Add downloadable charts.", "Add a short public-facing interpretation panel."]
    return ["Expand the dataset.", "Add human review notes.", "Compare results across at least two methods."]


def build_data_required(request: ExtensionFinderRequest, candidate: dict[str, Any]) -> str:
    availability = candidate["data_availability"]
    if availability == "synthetic":
        return "Synthetic or toy data should be enough for the first MVP, with paper chunks used only as motivation and citations."
    if availability == "public":
        return "Use public datasets or public web/source documents where available, plus a small manually checked sample."
    if availability == "needs_supervisor":
        return "Likely needs supervisor guidance for domain data; start with a public or synthetic substitute if access is delayed."
    if availability == "private":
        return "Private or sensitive data may be required; scope the MVP around anonymized, synthetic, or public substitute data."
    return "Data availability is unknown from the retrieved chunks; verify data access with the supervisor before committing to scope."


def build_evaluation_plan(request: ExtensionFinderRequest) -> str:
    if request.project_type == "software prototype":
        return "Evaluate with 5-10 task scenarios, record task success, citation/source correctness, latency, and a short usefulness review."
    if request.project_type == "data analysis":
        return "Evaluate by checking reproducibility, data quality notes, sensitivity to assumptions, and whether results answer the stated question."
    if request.project_type == "ML experiment":
        return "Evaluate against a baseline using precision/recall or task-specific metrics, plus qualitative error analysis on failed cases."
    if request.project_type == "literature/systematic review support":
        return "Evaluate extraction accuracy against a small hand-labeled review set and track reviewer time saved."
    if request.project_type == "dashboard/visualization":
        return "Evaluate with representative users on findability, chart correctness, and whether the dashboard supports the target decision."
    return "Define a small benchmark before implementation and report success rate, failure cases, and limits."


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
    if gap.get("support_status") != "explicit_in_paper":
        warnings.append("No explicit future-work or limitation statement was found for this recommendation.")
    if candidate["skills_gap"]:
        warnings.append("Some required skills are not in the student profile.")
    if candidate["data_availability"] == "unknown":
        warnings.append("Data availability is unknown and should be checked before scoping the project.")
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
        created_at=datetime.fromisoformat(response["created_at"]),
    )
    session.add(record)
    session.commit()


def serialize_recommendation(record: ThesisRecommendation) -> dict[str, Any]:
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
        "created_at": record.created_at.isoformat(),
    }


def recommendation_diagnostics(session: Session) -> dict[str, Any]:
    records = list(session.exec(select(ThesisRecommendation)).all())
    searchable_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    searchable_papers = session.exec(select(func.count(func.distinct(Chunk.paper_id))).select_from(Chunk)).one()
    last_record = max((record.created_at for record in records), default=None)
    return {
        "total_recommendation_runs": len(records),
        "total_recommendations_generated": sum(len(record.recommendations_json or []) for record in records),
        "grounded_runs": sum(1 for record in records if record.grounding_status == "grounded"),
        "partial_runs": sum(1 for record in records if record.grounding_status == "partial"),
        "unsupported_runs": sum(1 for record in records if record.grounding_status == "unsupported"),
        "searchable_chunks": searchable_chunks,
        "searchable_papers": searchable_papers,
        "default_provider": DEFAULT_PROVIDER,
        "last_recommendation_timestamp": last_record.isoformat() if last_record else None,
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


def data_feasibility_score(data_constraints: str, text_blob: str) -> float:
    availability = infer_data_availability(data_constraints, text_blob)
    return {
        "public": 1.0,
        "synthetic": 0.85,
        "needs_supervisor": 0.55,
        "unknown": 0.45,
        "private": 0.25,
    }[availability]


def infer_data_availability(data_constraints: str, text_blob: str) -> Literal["public", "needs_supervisor", "private", "synthetic", "unknown"]:
    constraints = data_constraints.lower()
    lowered = text_blob.lower()
    if "no external" in constraints or "synthetic" in constraints:
        return "synthetic"
    if "private" in lowered or "confidential" in lowered or "proprietary" in lowered:
        return "private"
    if "supervisor" in constraints or "needs supervisor" in constraints:
        return "needs_supervisor"
    if "public" in constraints or any(term in lowered for term in ("public data", "open data", "dataset", "benchmark")):
        return "public"
    return "unknown"


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


def infer_difficulty(request: ExtensionFinderRequest, text_blob: str) -> Difficulty:
    lowered = text_blob.lower()
    if request.preferred_difficulty == "hard":
        return "hard"
    if any(term in lowered for term in ("deep learning", "optimization", "multi-agent", "large language model")):
        return "hard" if request.preferred_difficulty == "hard" else "medium"
    if request.project_type == "ML experiment" and request.preferred_difficulty == "easy":
        return "medium"
    return request.preferred_difficulty


def difficulty_match_score(preferred: str, inferred: str) -> float:
    if preferred == inferred:
        return 1.0
    if {preferred, inferred} == {"easy", "medium"} or {preferred, inferred} == {"medium", "hard"}:
        return 0.65
    return 0.3


def infer_risk_level(request: ExtensionFinderRequest, skills_gap: list[str], text_blob: str) -> Literal["low", "medium", "high"]:
    availability = infer_data_availability(request.data_constraints, text_blob)
    difficulty = infer_difficulty(request, text_blob)
    if availability in {"private", "unknown"} and difficulty == "hard":
        return "high"
    if availability == "private" or len(skills_gap) >= 4:
        return "high"
    if availability == "unknown" or skills_gap or difficulty == "hard":
        return "medium"
    return "low"


def max_result_score(results: list[dict[str, Any]]) -> float:
    return max((float(result.get("scores", {}).get("combined") or 0.0) for result in results), default=0.0)


def lexical_overlap(profile_terms: set[str], text_terms: set[str]) -> float:
    if not profile_terms or not text_terms:
        return 0.0
    return round(len(profile_terms.intersection(text_terms)) / len(profile_terms), 4)


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
    recommend.add_argument("--mode", default="hybrid", choices=["keyword", "semantic", "hybrid"])
    recommend.add_argument("--provider", default="auto")
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
        response = recommend_extensions(session, request)
    print_cli_response(response)


if __name__ == "__main__":
    main()
