from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator
from sqlmodel import Session, func, select

from app.db import create_db_and_tables, engine
from app.evaluation.statistics import bootstrap_mean_interval, paired_bootstrap_mean_difference
from app.indexing.retriever import retrieve
from app.intelligence.extension_recommender import (
    SCORE_WEIGHTS,
    ExtensionFinderRequest,
    build_retrieval_query,
    clean_markup,
    evidence_only_baseline,
    group_results_by_paper,
    recommend_extensions,
    score_candidate_papers,
    skill_is_covered,
    timeline_fits,
    validated_score_weights,
)
from app.models import Chunk, Paper, ThesisRecommendation


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILES_PATH = PROJECT_ROOT / "data/evaluation/recommendation_profiles_v1.jsonl"
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "data/evaluation/recommendation_profiles_v1.schema.json"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "data/evaluation/recommendation_proxy_review_prompt_v1.md"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts/phase4/recommendation_proxy_v1"
DEFAULT_DENSE_MANIFEST_PATH = PROJECT_ROOT / "data/indexes/dense_embeddings.manifest.json"

REVIEW_SEEDS = (2026071401, 2026071402)
BOOTSTRAP_SEED = 2026071403
BOOTSTRAP_REPETITIONS = 10_000
TOP_K = 3

FULL_CRITERIA = (
    "paper_relevance",
    "source_fidelity",
    "fact_future_gap_suggestion_separation",
    "novelty_caution",
    "skills_time_data_feasibility",
    "mvp_scope",
    "stretch_goal_appropriateness",
    "risk_calibration",
    "required_skills",
    "evaluation_plan_quality",
    "usefulness_as_ai_proxy",
)
BASELINE_CRITERIA = ("paper_relevance", "source_fidelity")
JUDGMENT_VALUES = {"pass": 1.0, "partial": 0.5, "fail": 0.0, "not_applicable": None}

BASE_SKILLS_BY_TYPE = {
    "software prototype": {"Python", "FastAPI", "React", "API design", "evaluation"},
    "data analysis": {"Python", "statistics", "data cleaning", "visualization"},
    "ML experiment": {"Python", "machine learning", "data preprocessing", "evaluation"},
    "literature/systematic review support": {"research methods", "literature review", "data extraction", "Python"},
    "dashboard/visualization": {"visualization", "React", "data cleaning", "UI design"},
    "other": {"Python", "research methods", "evaluation"},
}

EXPLICIT_FUTURE_PATTERNS = (
    r"\bfuture work\b",
    r"\bfuture research\b",
    r"\bfuture studies\b",
    r"\bfurther research\b",
    r"\blimitations?\b",
    r"\bremains? to be\b",
    r"\bcould be extended\b",
    r"\bwe (?:plan|intend|recommend|propose)\b",
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def stable_json_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def load_profiles(path: Path, schema_path: Path) -> list[dict[str, Any]]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    profiles: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        profile = json.loads(raw_line)
        errors = sorted(validator.iter_errors(profile), key=lambda error: list(error.path))
        if errors:
            detail = "; ".join(error.message for error in errors)
            raise ValueError(f"invalid profile at line {line_number}: {detail}")
        profiles.append(profile)
    validate_profile_coverage(profiles)
    return profiles


def validate_profile_coverage(profiles: Sequence[Mapping[str, Any]]) -> None:
    if not 20 <= len(profiles) <= 30:
        raise ValueError("recommendation proxy evaluation requires 20-30 profiles")
    profile_ids = [str(profile["profile_id"]) for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("profile_id values must be unique")
    required_values = {
        "available_time": {"2 weeks", "1 month", "semester"},
        "preferred_difficulty": {"easy", "medium", "hard"},
        "project_type": set(BASE_SKILLS_BY_TYPE),
    }
    for field, expected in required_values.items():
        observed = {str(profile[field]) for profile in profiles}
        if not expected.issubset(observed):
            raise ValueError(f"profile coverage missing {field}: {sorted(expected - observed)}")
    if not all(profile.get("avoid_topics") for profile in profiles):
        raise ValueError("every profile must exercise avoid_topics")
    constraints = {str(profile["data_constraints"]) for profile in profiles}
    required_constraints = {
        "public data preferred",
        "synthetic data acceptable",
        "no external data",
        "needs supervisor data",
    }
    if not required_constraints.issubset(constraints):
        raise ValueError(f"profile coverage missing data constraints: {sorted(required_constraints - constraints)}")


def request_from_profile(profile: Mapping[str, Any], *, top_k: int = TOP_K) -> ExtensionFinderRequest:
    return ExtensionFinderRequest(
        interests=str(profile["interests"]),
        skills=list(profile["skills"]),
        available_time=str(profile["available_time"]),
        project_type=str(profile["project_type"]),
        data_constraints=str(profile["data_constraints"]),
        preferred_difficulty=str(profile["preferred_difficulty"]),
        preferred_topics=list(profile["preferred_topics"]),
        avoid_topics=list(profile["avoid_topics"]),
        top_k=top_k,
        retrieval_mode=str(profile["retrieval_mode"]),
        provider="offline_deterministic",
    )


def corpus_provenance(session: Session, dense_manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(dense_manifest_path.read_text(encoding="utf-8"))
    corpus = manifest.get("corpus") or {}
    eligible_chunk_count = session.exec(
        select(func.count())
        .select_from(Chunk)
        .join(Paper, Chunk.paper_id == Paper.paper_id)
        .where(Paper.corpus_eligibility_status == "eligible")
    ).one()
    eligible_paper_count = session.exec(
        select(func.count(func.distinct(Chunk.paper_id)))
        .select_from(Chunk)
        .join(Paper, Chunk.paper_id == Paper.paper_id)
        .where(Paper.corpus_eligibility_status == "eligible")
    ).one()
    if corpus.get("eligible_chunk_count") != eligible_chunk_count:
        raise RuntimeError(
            "dense manifest/corpus mismatch: "
            f"manifest={corpus.get('eligible_chunk_count')} live={eligible_chunk_count}"
        )
    if corpus.get("eligible_paper_count") != eligible_paper_count:
        raise RuntimeError(
            "dense manifest/paper mismatch: "
            f"manifest={corpus.get('eligible_paper_count')} live={eligible_paper_count}"
        )
    return {
        "snapshot_id": corpus.get("snapshot_id"),
        "snapshot_hash": corpus.get("snapshot_hash"),
        "eligible_chunk_count": eligible_chunk_count,
        "eligible_paper_count": eligible_paper_count,
        "eligibility_boundary": "Paper.corpus_eligibility_status == 'eligible'",
        "topic_author_link_rows_used": False,
        "dense_manifest_path": str(dense_manifest_path.relative_to(PROJECT_ROOT)),
        "dense_manifest_sha256": sha256_file(dense_manifest_path),
        "dense_index_build_id": manifest.get("build_id"),
        "dense_configuration": manifest.get("configuration"),
    }


def load_chunk_evidence(session: Session) -> dict[str, dict[str, Any]]:
    rows = session.exec(
        select(Chunk, Paper)
        .join(Paper, Chunk.paper_id == Paper.paper_id)
        .where(Paper.corpus_eligibility_status == "eligible")
    ).all()
    return {
        chunk.chunk_id: {
            "chunk_id": chunk.chunk_id,
            "paper_id": chunk.paper_id,
            "paper_title": paper.title,
            "section": chunk.section,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": chunk.text,
            "source_hash": chunk.source_hash,
        }
        for chunk, paper in rows
    }


def execute_profiles(
    session: Session,
    profiles: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    outputs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stored_before = session.exec(select(func.count()).select_from(ThesisRecommendation)).one()
    for profile in profiles:
        profile_id = str(profile["profile_id"])
        try:
            request = request_from_profile(profile)
            retrieval_trace = retrieve(
                session,
                build_retrieval_query(request),
                mode=request.retrieval_mode,
                top_k=max(request.top_k * 6, request.top_k),
                scope="technical",
            )
            baseline = evidence_only_baseline(
                session,
                request,
                retrieval_response=retrieval_trace,
                retrieval_scope="technical",
            )
            full = recommend_extensions(
                session,
                request,
                persist=False,
                retrieval_response=retrieval_trace,
                retrieval_scope="technical",
            )
            outputs.append(
                {
                    "profile_id": profile_id,
                    "request_hash": stable_json_hash(request.model_dump()),
                    "retrieval_trace": retrieval_trace,
                    "baseline": baseline,
                    "full_finder": full,
                }
            )
        except Exception as exc:  # pragma: no cover - retained as experiment evidence
            failures.append(
                {
                    "profile_id": profile_id,
                    "stage": "execution",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    stored_after = session.exec(select(func.count()).select_from(ThesisRecommendation)).one()
    if stored_after != stored_before:
        raise RuntimeError(
            "transient recommendation evaluation mutated live ThesisRecommendation rows: "
            f"before={stored_before} after={stored_after}"
        )
    return outputs, failures


def build_reviews(
    profiles: Sequence[Mapping[str, Any]],
    outputs: Sequence[Mapping[str, Any]],
    chunk_evidence: Mapping[str, Mapping[str, Any]],
    *,
    prompt_sha256: str,
    code_sha256: str,
) -> list[dict[str, Any]]:
    profiles_by_id = {str(profile["profile_id"]): profile for profile in profiles}
    review_units: list[tuple[str, str, int, Mapping[str, Any]]] = []
    for output in outputs:
        profile_id = str(output["profile_id"])
        for paper in output["baseline"].get("papers", []):
            review_units.append((profile_id, "evidence_only", int(paper["rank"]), paper))
        for recommendation in output["full_finder"].get("recommendations", []):
            review_units.append((profile_id, "full_finder", int(recommendation["rank"]), recommendation))

    records: list[dict[str, Any]] = []
    for pass_number, seed in enumerate(REVIEW_SEEDS, start=1):
        shuffled = list(review_units)
        random.Random(seed).shuffle(shuffled)
        for review_order, (profile_id, arm, rank, item) in enumerate(shuffled, start=1):
            profile = profiles_by_id[profile_id]
            if arm == "evidence_only":
                judgments, taxonomy = review_baseline_paper(profile, item, chunk_evidence, pass_number=pass_number)
                source_evidence = item.get("passages", [])
                paper_id = item.get("paper_id")
                paper_title = item.get("paper_title")
            else:
                judgments, taxonomy = review_full_recommendation(profile, item, chunk_evidence, pass_number=pass_number)
                source_evidence = item.get("citations", [])
                paper_id = item.get("paper_id")
                paper_title = item.get("paper_title")
            records.append(
                {
                    "review_id": f"proxy-v1-pass{pass_number}-{profile_id}-{arm}-{rank}",
                    "review_pass": pass_number,
                    "review_seed": seed,
                    "review_order": review_order,
                    "reviewer_type": "ai",
                    "reviewer_identity": "codex-ai-source-audit",
                    "review_method": "deterministic source-inspection rubric authored and executed by Codex",
                    "reviewer_lens": "support_first" if pass_number == 1 else "contradiction_first",
                    "independence_note": "Repeatability pass by one AI-assisted procedure; not human inter-rater reliability.",
                    "prompt_sha256": prompt_sha256,
                    "review_code_sha256": code_sha256,
                    "profile_id": profile_id,
                    "arm": arm,
                    "rank": rank,
                    "paper_id": paper_id,
                    "paper_title": paper_title,
                    "judgments": judgments,
                    "error_taxonomy": taxonomy,
                    "source_evidence": source_evidence,
                }
            )
    return records


def review_baseline_paper(
    profile: Mapping[str, Any],
    paper: Mapping[str, Any],
    chunk_evidence: Mapping[str, Mapping[str, Any]],
    *,
    pass_number: int,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    relevance = relevance_judgment(profile, paper, evidence_key="passages", pass_number=pass_number)
    fidelity = citation_fidelity_judgment(paper.get("passages", []), chunk_evidence, expected_paper_id=str(paper["paper_id"]))
    judgments = {
        "paper_relevance": relevance,
        "source_fidelity": fidelity,
        **{
            criterion: {
                "judgment": "not_applicable",
                "rationale": "Evidence-only baseline deliberately does not generate advisory content.",
            }
            for criterion in FULL_CRITERIA
            if criterion not in BASELINE_CRITERIA
        },
    }
    return judgments, taxonomy_from_judgments(judgments)


def review_full_recommendation(
    profile: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    chunk_evidence: Mapping[str, Mapping[str, Any]],
    *,
    pass_number: int,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    relevance = relevance_judgment(profile, recommendation, evidence_key="citations", pass_number=pass_number)
    fidelity = citation_fidelity_judgment(
        recommendation.get("citations", []),
        chunk_evidence,
        expected_paper_id=str(recommendation["paper_id"]),
        facts=recommendation.get("source_supported_facts", []),
    )
    separation = separation_judgment(recommendation, chunk_evidence)
    novelty = novelty_judgment(recommendation)
    feasibility = feasibility_judgment(profile, recommendation)
    mvp = mvp_judgment(profile, recommendation)
    stretch = stretch_judgment(recommendation)
    risk = risk_judgment(profile, recommendation)
    skills = required_skills_judgment(profile, recommendation)
    evaluation = evaluation_plan_judgment(profile, recommendation)
    core = [relevance, fidelity, separation, novelty, feasibility, mvp, stretch, risk, skills, evaluation]
    strict_passes = sum(judgment["judgment"] == "pass" for judgment in core)
    any_fail = any(judgment["judgment"] == "fail" for judgment in core)
    if relevance["judgment"] == "fail" or fidelity["judgment"] == "fail" or any_fail:
        usefulness_status = "fail"
        usefulness_reason = "At least one core relevance, evidence, or advisory-quality criterion failed."
    elif strict_passes >= 8:
        usefulness_status = "pass"
        usefulness_reason = f"The source-backed profile audit passed {strict_passes} of 10 component criteria."
    else:
        usefulness_status = "partial"
        usefulness_reason = f"The output is potentially useful but passed only {strict_passes} of 10 component criteria."
    judgments = {
        "paper_relevance": relevance,
        "source_fidelity": fidelity,
        "fact_future_gap_suggestion_separation": separation,
        "novelty_caution": novelty,
        "skills_time_data_feasibility": feasibility,
        "mvp_scope": mvp,
        "stretch_goal_appropriateness": stretch,
        "risk_calibration": risk,
        "required_skills": skills,
        "evaluation_plan_quality": evaluation,
        "usefulness_as_ai_proxy": {"judgment": usefulness_status, "rationale": usefulness_reason},
    }
    return judgments, taxonomy_from_judgments(judgments)


def relevance_judgment(
    profile: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    evidence_key: str,
    pass_number: int,
) -> dict[str, Any]:
    title = normalize_text(str(item.get("paper_title") or ""))
    evidence = normalize_text(" ".join(str(source.get("snippet") or "") for source in item.get(evidence_key, [])))
    terms = [normalize_text(str(term)) for term in profile["relevance_terms"]]
    title_hits = sorted(term for term in terms if term and term in title)
    evidence_hits = sorted(term for term in terms if term and term in evidence)
    avoid_terms = [normalize_text(str(term)) for term in profile.get("avoid_topics", [])]
    avoid_hits = sorted(term for term in avoid_terms if term and (term in title or term in evidence))
    unique_hits = sorted(set(title_hits + evidence_hits))
    if title_hits or len(unique_hits) >= 2 or (pass_number == 1 and unique_hits):
        status = "pass" if not avoid_hits else "partial"
        rationale = (
            f"Profile-relevance evidence matched {unique_hits or title_hits}; "
            f"avoid-topic matches were {avoid_hits or 'none'}."
        )
    elif unique_hits:
        status = "partial"
        rationale = f"Only one evidence-level relevance signal matched in the contradiction-first pass: {unique_hits}."
    else:
        status = "fail"
        rationale = "Neither the title nor cited passages matched the profile's pre-registered relevance concepts."
    return {
        "judgment": status,
        "rationale": rationale,
        "observed_relevance_terms": unique_hits,
        "observed_avoid_terms": avoid_hits,
    }


def citation_fidelity_judgment(
    citations: Sequence[Mapping[str, Any]],
    chunk_evidence: Mapping[str, Mapping[str, Any]],
    *,
    expected_paper_id: str,
    facts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not citations:
        return {"judgment": "fail", "rationale": "No cited source passage was returned."}
    problems: list[str] = []
    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        source = chunk_evidence.get(chunk_id)
        if source is None:
            problems.append(f"missing eligible chunk {chunk_id or '<blank>'}")
            continue
        if source["paper_id"] != expected_paper_id or citation.get("paper_id") != expected_paper_id:
            problems.append(f"paper mismatch for {chunk_id}")
        snippet = normalize_text(str(citation.get("snippet") or ""))
        source_text = normalize_text(str(source.get("text") or ""))
        if snippet and snippet not in source_text and token_containment(snippet, source_text) < 0.9:
            problems.append(f"snippet mismatch for {chunk_id}")
        for field in ("page_start", "page_end"):
            if citation.get(field) != source.get(field):
                problems.append(f"{field} mismatch for {chunk_id}")
    cited_ids = {str(citation.get("chunk_id") or "") for citation in citations}
    for fact in facts:
        chunk_id = str(fact.get("chunk_id") or "")
        if chunk_id not in cited_ids or chunk_id not in chunk_evidence:
            problems.append(f"fact not mapped to cited eligible chunk {chunk_id or '<blank>'}")
        claim = normalize_text(str(fact.get("claim") or ""))
        snippet = normalize_text(str(fact.get("snippet") or ""))
        if claim and claim not in snippet:
            problems.append(f"fact claim not contained in its displayed snippet {chunk_id}")
    if problems:
        return {"judgment": "fail", "rationale": "; ".join(sorted(set(problems)))}
    return {
        "judgment": "pass",
        "rationale": f"All {len(citations)} citations resolve to the expected eligible paper, pages, and source text.",
    }


def separation_judgment(
    recommendation: Mapping[str, Any],
    chunk_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    gap = recommendation.get("identified_gap") or {}
    status = str(gap.get("support_status") or "")
    extension_summary = str(recommendation.get("extension_summary") or "")
    gap_text = str(gap.get("text") or "")
    source_ids = [str(value) for value in gap.get("source_chunk_ids", []) if value]
    source_text = " ".join(str(chunk_evidence.get(chunk_id, {}).get("text") or "") for chunk_id in source_ids)
    source_sections = {str(chunk_evidence.get(chunk_id, {}).get("section") or "").lower() for chunk_id in source_ids}
    explicit_signal = any(re.search(pattern, source_text, flags=re.IGNORECASE) for pattern in EXPLICIT_FUTURE_PATTERNS)
    reference_only = bool(source_sections) and all("reference" in section for section in source_sections)
    problems: list[str] = []
    if status not in {"explicit_in_paper", "inferred_from_paper", "not_found"}:
        problems.append(f"unknown gap support status {status!r}")
    if status == "explicit_in_paper" and (not explicit_signal or reference_only):
        problems.append("explicit gap label lacks non-reference limitation/future-work evidence")
    if status != "explicit_in_paper" and "inferred" not in gap_text.lower() and "not found" not in gap_text.lower():
        problems.append("inferred/missing gap is not labeled in the displayed gap text")
    if "suggested extension" not in extension_summary.lower() or "not a verified claim" not in extension_summary.lower():
        problems.append("new suggestion is not clearly separated from paper claims")
    if not recommendation.get("source_supported_facts"):
        problems.append("paper facts are not separated into a source-supported field")
    if problems:
        return {"judgment": "fail", "rationale": "; ".join(problems)}
    return {
        "judgment": "pass",
        "rationale": f"Facts, gap status ({status}), and the system-suggested extension are separately labeled and cited.",
    }


def novelty_judgment(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    summary = str(recommendation.get("extension_summary") or "")
    combined = f"{summary} {' '.join(str(value) for value in recommendation.get('warnings', []))}".lower()
    unqualified_novelty = bool(re.search(r"\b(?:novel|first-ever|original contribution|guaranteed new)\b", combined))
    cautious = "suggested extension" in combined and "not a verified claim" in combined
    if unqualified_novelty:
        return {"judgment": "fail", "rationale": "The generated text makes an unverified novelty claim."}
    if not cautious:
        return {"judgment": "partial", "rationale": "No novelty claim appeared, but the suggestion caution was incomplete."}
    return {
        "judgment": "pass",
        "rationale": "The idea is labeled as a system suggestion and does not claim novelty or originality.",
    }


def feasibility_judgment(profile: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    warnings = " ".join(str(value) for value in recommendation.get("warnings", [])).lower()
    why = str(recommendation.get("why_it_fits_student") or "").lower()
    implementation_time = str(recommendation.get("implementation_time") or "unknown")
    time_ok = timeline_fits(str(profile["available_time"]), implementation_time)
    time_candid = time_ok or ("exceeds" in why and "scope" in why)
    skills_gap = list(recommendation.get("skills_gap", []))
    skills_candid = not skills_gap or "skill" in warnings
    availability = str(recommendation.get("data_availability") or "unknown")
    data_text = str(recommendation.get("data_required") or "").lower()
    data_candid = availability not in {"unknown", "private", "needs_supervisor"} or any(
        marker in f"{warnings} {data_text}" for marker in ("unknown", "private", "supervisor", "verify", "substitute")
    )
    if not (time_candid and skills_candid and data_candid):
        return {
            "judgment": "fail",
            "rationale": f"Constraint warnings incomplete: time={time_candid}, skills={skills_candid}, data={data_candid}.",
        }
    if not time_ok or skills_gap or availability in {"unknown", "private", "needs_supervisor"}:
        return {
            "judgment": "partial",
            "rationale": (
                "The output candidly flags unresolved feasibility constraints "
                f"(time_fit={time_ok}, skill_gaps={len(skills_gap)}, data={availability}); external confirmation remains necessary."
            ),
        }
    return {
        "judgment": "pass",
        "rationale": "The stated time, supplied skills, and indicated data route are internally consistent; this remains only a proxy judgment.",
    }


def mvp_judgment(profile: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    text = str(recommendation.get("mvp_scope") or "").lower()
    narrow_markers = ("small", "one ", "baseline", "minimal", "core", "curated")
    type_markers = {
        "software prototype": ("prototype", "workflow", "working"),
        "data analysis": ("analysis", "notebook", "script"),
        "ML experiment": ("model", "experiment", "baseline"),
        "literature/systematic review support": ("review", "papers", "evidence"),
        "dashboard/visualization": ("dashboard", "visual", "filters"),
        "other": ("research question", "artifact", "evaluate"),
    }[str(profile["project_type"])]
    if not text:
        return {"judgment": "fail", "rationale": "No MVP scope was supplied."}
    if not any(marker in text for marker in narrow_markers) or not any(marker in text for marker in type_markers):
        return {"judgment": "partial", "rationale": "The MVP is present but not both narrow and project-type specific."}
    return {"judgment": "pass", "rationale": "The MVP is bounded and matches the requested project type."}


def stretch_judgment(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    goals = [str(value).strip() for value in recommendation.get("stretch_goals", []) if str(value).strip()]
    if not goals:
        return {"judgment": "fail", "rationale": "No stretch goals were supplied."}
    if len(set(goals)) != len(goals):
        return {"judgment": "fail", "rationale": "Stretch goals contain duplicates."}
    if not 2 <= len(goals) <= 4:
        return {"judgment": "partial", "rationale": f"The {len(goals)} stretch goals are not a compact 2-4 item extension set."}
    return {"judgment": "pass", "rationale": f"The {len(goals)} distinct goals extend rather than replace the MVP."}


def risk_judgment(profile: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    availability = str(recommendation.get("data_availability") or "unknown")
    difficulty = str(recommendation.get("difficulty") or "medium")
    gap_count = len(recommendation.get("skills_gap", []))
    expected = "low"
    if (availability in {"private", "unknown"} and difficulty == "hard") or availability == "private" or gap_count >= 4:
        expected = "high"
    elif availability == "unknown" or gap_count or difficulty == "hard":
        expected = "medium"
    observed = str(recommendation.get("risk_level") or "")
    if observed != expected:
        return {"judgment": "fail", "rationale": f"Risk was {observed!r}, but disclosed constraints imply {expected!r}."}
    return {
        "judgment": "pass",
        "rationale": f"Risk={observed} is internally calibrated to difficulty, {gap_count} skill gaps, and data status {availability}.",
    }


def required_skills_judgment(profile: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    required = {str(value) for value in recommendation.get("required_skills", [])}
    expected_base = BASE_SKILLS_BY_TYPE[str(profile["project_type"])]
    missing = sorted(expected_base - required)
    observed_gaps = {str(value) for value in recommendation.get("skills_gap", [])}
    expected_gaps = {skill for skill in required if not skill_is_covered(skill, list(profile["skills"]))}
    if missing or observed_gaps != expected_gaps:
        return {
            "judgment": "fail",
            "rationale": f"Missing base skills={missing}; reported/derived gap mismatch={sorted(observed_gaps ^ expected_gaps)}.",
        }
    return {
        "judgment": "pass",
        "rationale": f"The required-skill list covers the project type and all {len(expected_gaps)} uncovered skills are surfaced.",
    }


def evaluation_plan_judgment(profile: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    plan = str(recommendation.get("evaluation_plan") or "").lower()
    measurement_markers = (
        "accuracy", "precision", "recall", "metric", "success", "latency", "correctness",
        "reproducibility", "sensitivity", "error analysis", "findability", "time saved", "benchmark",
    )
    review_markers = ("qualitative", "review", "representative users", "limitations", "failure")
    has_measure = any(marker in plan for marker in measurement_markers)
    has_review = any(marker in plan for marker in review_markers)
    if not plan or not has_measure:
        return {"judgment": "fail", "rationale": "The evaluation plan lacks an observable metric or success criterion."}
    if not has_review:
        return {"judgment": "partial", "rationale": "The plan has measurable criteria but no explicit review/error/limitation component."}
    return {
        "judgment": "pass",
        "rationale": "The plan combines observable criteria with review, error, user, or limitation analysis.",
    }


def taxonomy_from_judgments(judgments: Mapping[str, Mapping[str, Any]]) -> list[str]:
    labels = {
        "paper_relevance": "off_topic_paper",
        "source_fidelity": "citation_or_source_mismatch",
        "fact_future_gap_suggestion_separation": "claim_type_or_gap_overstatement",
        "novelty_caution": "uncautious_novelty_language",
        "skills_time_data_feasibility": "unresolved_feasibility_constraint",
        "mvp_scope": "generic_or_unbounded_mvp",
        "stretch_goal_appropriateness": "weak_stretch_goals",
        "risk_calibration": "risk_miscalibration",
        "required_skills": "skills_mismatch",
        "evaluation_plan_quality": "weak_evaluation_plan",
        "usefulness_as_ai_proxy": "low_proxy_usefulness",
    }
    return [
        labels[criterion]
        for criterion, judgment in judgments.items()
        if criterion in labels and judgment.get("judgment") in {"partial", "fail"}
    ]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", clean_markup(value)).strip().lower()


def token_containment(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def sensitivity_weight_sets() -> dict[str, dict[str, float]]:
    variants = {"default_hand_authored": validated_score_weights()}
    for name in SCORE_WEIGHTS:
        for direction, factor in (("minus25pct", 0.75), ("plus25pct", 1.25), ("zero", 0.0)):
            changed = dict(SCORE_WEIGHTS)
            changed[name] *= factor
            variants[f"{name}_{direction}"] = validated_score_weights(changed)
    return variants


def execute_sensitivity(
    session: Session,
    profiles: Sequence[Mapping[str, Any]],
    outputs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    variants = sensitivity_weight_sets()
    outputs_by_profile = {str(output["profile_id"]): output for output in outputs}
    per_profile: list[dict[str, Any]] = []
    for profile in profiles:
        request = request_from_profile(profile)
        retrieval = outputs_by_profile[str(profile["profile_id"])]["retrieval_trace"]
        groups = group_results_by_paper(retrieval.get("results", []))
        rankings: dict[str, list[dict[str, Any]]] = {}
        for variant_name, weights in variants.items():
            candidates = score_candidate_papers(groups, request, score_weights=weights)
            rankings[variant_name] = [
                {
                    "rank": rank,
                    "paper_id": candidate["paper_id"],
                    "paper_title": candidate["paper_title"],
                    "fit_score": candidate["fit_score"],
                    "score_breakdown": candidate["component_scores"],
                }
                for rank, candidate in enumerate(candidates[: request.top_k], start=1)
            ]
        per_profile.append({"profile_id": profile["profile_id"], "rankings": rankings})

    aggregate: dict[str, Any] = {}
    for variant_name in variants:
        default_top = {
            str(row["profile_id"]): [item["paper_id"] for item in row["rankings"]["default_hand_authored"]]
            for row in per_profile
        }
        variant_top = {
            str(row["profile_id"]): [item["paper_id"] for item in row["rankings"][variant_name]]
            for row in per_profile
        }
        top1_retention = [
            float(bool(default_top[profile_id] and variant_top[profile_id] and default_top[profile_id][0] == variant_top[profile_id][0]))
            for profile_id in default_top
        ]
        set_overlap = [
            jaccard(set(default_top[profile_id]), set(variant_top[profile_id]))
            for profile_id in default_top
        ]
        rank_displacement = [
            mean_rank_displacement(default_top[profile_id], variant_top[profile_id])
            for profile_id in default_top
        ]
        aggregate[variant_name] = {
            "weights": variants[variant_name],
            "top1_retention_rate": fmean(top1_retention),
            "mean_top3_set_jaccard": fmean(set_overlap),
            "mean_rank_displacement": fmean(rank_displacement),
            "top1_retention_ci": bootstrap_mean_interval(
                top1_retention,
                repetitions=BOOTSTRAP_REPETITIONS,
                seed=BOOTSTRAP_SEED,
                retain_replicates=False,
            ),
            "top3_set_jaccard_ci": bootstrap_mean_interval(
                set_overlap,
                repetitions=BOOTSTRAP_REPETITIONS,
                seed=BOOTSTRAP_SEED + 1,
                retain_replicates=False,
            ),
        }
    return {
        "weight_origin": "hand_authored_heuristic_not_tuned",
        "local_perturbations": "Each component is independently multiplied by 0.75, 1.25, or 0.0 and all weights are renormalized.",
        "profiles": per_profile,
        "aggregate": aggregate,
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def mean_rank_displacement(default: Sequence[str], candidate: Sequence[str]) -> float:
    if not default and not candidate:
        return 0.0
    cutoff = max(len(default), len(candidate), 1)
    default_rank = {paper_id: rank for rank, paper_id in enumerate(default, start=1)}
    candidate_rank = {paper_id: rank for rank, paper_id in enumerate(candidate, start=1)}
    union = set(default_rank) | set(candidate_rank)
    return fmean(abs(default_rank.get(paper_id, cutoff + 1) - candidate_rank.get(paper_id, cutoff + 1)) for paper_id in union)


def aggregate_reviews(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pass_one = [review for review in reviews if review["review_pass"] == 1]
    metrics: dict[str, Any] = {}
    for arm in ("evidence_only", "full_finder"):
        arm_reviews = [review for review in pass_one if review["arm"] == arm]
        criteria = BASELINE_CRITERIA if arm == "evidence_only" else FULL_CRITERIA
        criteria_metrics: dict[str, Any] = {}
        for criterion in criteria:
            by_profile: dict[str, list[float]] = defaultdict(list)
            strict_by_profile: dict[str, list[float]] = defaultdict(list)
            counts: Counter[str] = Counter()
            for review in arm_reviews:
                status = str(review["judgments"][criterion]["judgment"])
                counts[status] += 1
                value = JUDGMENT_VALUES[status]
                if value is not None:
                    by_profile[str(review["profile_id"])].append(value)
                    strict_by_profile[str(review["profile_id"])].append(float(status == "pass"))
            profile_scores = [fmean(values) for values in by_profile.values() if values]
            strict_scores = [fmean(values) for values in strict_by_profile.values() if values]
            criteria_metrics[criterion] = {
                "counts": dict(sorted(counts.items())),
                "weighted_score": fmean(profile_scores) if profile_scores else None,
                "strict_pass_rate": fmean(strict_scores) if strict_scores else None,
                "weighted_score_ci": bootstrap_mean_interval(
                    profile_scores,
                    repetitions=BOOTSTRAP_REPETITIONS,
                    seed=BOOTSTRAP_SEED,
                    retain_replicates=False,
                ),
                "strict_pass_rate_ci": bootstrap_mean_interval(
                    strict_scores,
                    repetitions=BOOTSTRAP_REPETITIONS,
                    seed=BOOTSTRAP_SEED + 1,
                    retain_replicates=False,
                ),
            }
        metrics[arm] = {"reviewed_items": len(arm_reviews), "criteria": criteria_metrics}

    metrics["arm_comparison"] = compare_relevance_by_profile(pass_one)
    metrics["repeatability"] = review_repeatability(reviews)
    metrics["error_taxonomy"] = dict(
        sorted(Counter(label for review in pass_one for label in review["error_taxonomy"]).items())
    )
    return metrics


def compare_relevance_by_profile(pass_one: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, dict[str, list[float]]] = {
        "evidence_only": defaultdict(list),
        "full_finder": defaultdict(list),
    }
    paper_sets: dict[str, dict[str, set[str]]] = {
        "evidence_only": defaultdict(set),
        "full_finder": defaultdict(set),
    }
    for review in pass_one:
        arm = str(review["arm"])
        profile_id = str(review["profile_id"])
        status = str(review["judgments"]["paper_relevance"]["judgment"])
        value = JUDGMENT_VALUES[status]
        if value is not None:
            by_arm[arm][profile_id].append(value)
        paper_sets[arm][profile_id].add(str(review["paper_id"]))
    profile_ids = sorted(set(by_arm["evidence_only"]) & set(by_arm["full_finder"]))
    baseline = [fmean(by_arm["evidence_only"][profile_id]) for profile_id in profile_ids]
    full = [fmean(by_arm["full_finder"][profile_id]) for profile_id in profile_ids]
    overlaps = [
        jaccard(paper_sets["evidence_only"][profile_id], paper_sets["full_finder"][profile_id])
        for profile_id in profile_ids
    ]
    return {
        "unit": "profile",
        "profile_count": len(profile_ids),
        "baseline_mean_relevance_score": fmean(baseline),
        "full_finder_mean_relevance_score": fmean(full),
        "full_minus_baseline_relevance": paired_bootstrap_mean_difference(
            baseline,
            full,
            repetitions=BOOTSTRAP_REPETITIONS,
            seed=BOOTSTRAP_SEED,
            retain_replicates=False,
        ),
        "mean_top3_paper_set_jaccard": fmean(overlaps),
        "paper_set_jaccard_ci": bootstrap_mean_interval(
            overlaps,
            repetitions=BOOTSTRAP_REPETITIONS,
            seed=BOOTSTRAP_SEED + 2,
            retain_replicates=False,
        ),
    }


def review_repeatability(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_key: dict[tuple[str, str, int], dict[int, Mapping[str, Any]]] = defaultdict(dict)
    for review in reviews:
        key = (str(review["profile_id"]), str(review["arm"]), int(review["rank"]))
        by_key[key][int(review["review_pass"])] = review
    agreement_flags: list[float] = []
    weighted_differences: list[float] = []
    compared = 0
    for passes in by_key.values():
        if set(passes) != {1, 2}:
            continue
        first = passes[1]["judgments"]
        second = passes[2]["judgments"]
        for criterion in sorted(set(first) & set(second)):
            left = str(first[criterion]["judgment"])
            right = str(second[criterion]["judgment"])
            if left == "not_applicable" or right == "not_applicable":
                continue
            compared += 1
            agreement_flags.append(float(left == right))
            weighted_differences.append(abs(float(JUDGMENT_VALUES[left]) - float(JUDGMENT_VALUES[right])))
    return {
        "method": "same-ai-procedure_fixed-rubric_two-shuffled-order-passes",
        "not_human_inter_rater_reliability": True,
        "review_seeds": list(REVIEW_SEEDS),
        "criterion_judgments_compared": compared,
        "exact_agreement": fmean(agreement_flags) if agreement_flags else None,
        "mean_absolute_score_difference": fmean(weighted_differences) if weighted_differences else None,
    }


def profile_coverage(profiles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "profile_count": len(profiles),
        "available_time": dict(sorted(Counter(str(profile["available_time"]) for profile in profiles).items())),
        "project_type": dict(sorted(Counter(str(profile["project_type"]) for profile in profiles).items())),
        "data_constraints": dict(sorted(Counter(str(profile["data_constraints"]) for profile in profiles).items())),
        "preferred_difficulty": dict(sorted(Counter(str(profile["preferred_difficulty"]) for profile in profiles).items())),
        "profiles_with_avoid_topics": sum(bool(profile.get("avoid_topics")) for profile in profiles),
        "profiles_with_no_declared_skills": sum(not profile.get("skills") for profile in profiles),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def run_evaluation(
    session: Session,
    *,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    dense_manifest_path: Path = DEFAULT_DENSE_MANIFEST_PATH,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    profiles = load_profiles(profiles_path, schema_path)
    corpus = corpus_provenance(session, dense_manifest_path)
    chunk_evidence = load_chunk_evidence(session)
    if len(chunk_evidence) != corpus["eligible_chunk_count"]:
        raise RuntimeError("eligible source-evidence map does not cover the frozen corpus")
    outputs, failures = execute_profiles(session, profiles)
    module_path = Path(__file__)
    reviews = build_reviews(
        profiles,
        outputs,
        chunk_evidence,
        prompt_sha256=sha256_file(prompt_path),
        code_sha256=sha256_file(module_path),
    )
    sensitivity = execute_sensitivity(session, profiles, outputs)
    aggregate = aggregate_reviews(reviews)
    completed_at = utc_now_iso()

    raw_outputs_path = output_dir / "raw_outputs.jsonl"
    pass_one_path = output_dir / "review_pass_1.jsonl"
    pass_two_path = output_dir / "review_pass_2.jsonl"
    sensitivity_path = output_dir / "weight_sensitivity.json"
    aggregate_path = output_dir / "aggregate_results.json"
    failures_path = output_dir / "failures.json"
    write_jsonl(raw_outputs_path, outputs)
    write_jsonl(pass_one_path, (review for review in reviews if review["review_pass"] == 1))
    write_jsonl(pass_two_path, (review for review in reviews if review["review_pass"] == 2))
    write_json(sensitivity_path, sensitivity)
    write_json(failures_path, failures)

    result = {
        "evaluation_id": "recommendation-proxy-v1",
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "complete" if not failures and len(outputs) == len(profiles) else "complete_with_failures",
        "reviewer_type": "ai",
        "reviewer_identity": "codex-ai-source-audit",
        "claim_boundary": {
            "is_ai_assisted_proxy_review": True,
            "is_student_validation": False,
            "is_supervisor_validation": False,
            "is_human_inter_rater_reliability": False,
            "is_novelty_search": False,
            "is_feasibility_guarantee": False,
        },
        "profile_coverage": profile_coverage(profiles),
        "execution": {
            "profiles_attempted": len(profiles),
            "profiles_completed": len(outputs),
            "failures": len(failures),
            "top_k": TOP_K,
            "persistence": False,
            "live_recommendation_rows_unchanged": True,
            "baseline": "same-query/same-retrieval evidence-only ranked-paper and source-passage arm",
            "full_finder": "offline deterministic Thesis Extension Finder",
        },
        "corpus": corpus,
        "recommendation_weights": {
            "default": SCORE_WEIGHTS,
            "origin": "hand_authored_heuristic_not_tuned",
        },
        "review_configuration": {
            "criteria": list(FULL_CRITERIA),
            "review_seeds": list(REVIEW_SEEDS),
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
            "confidence_level": 0.95,
            "review_prompt_path": str(prompt_path.relative_to(PROJECT_ROOT)),
            "review_prompt_sha256": sha256_file(prompt_path),
            "evaluation_code_path": str(module_path.relative_to(PROJECT_ROOT)),
            "evaluation_code_sha256": sha256_file(module_path),
            "git_commit_at_execution": git_commit(),
            "profiles_path": str(profiles_path.relative_to(PROJECT_ROOT)),
            "profiles_sha256": sha256_file(profiles_path),
            "profile_schema_sha256": sha256_file(schema_path),
        },
        "metrics": aggregate,
        "sensitivity_summary": sensitivity["aggregate"],
        "limitations": [
            "Profiles are synthetic and were not completed by students.",
            "Judgments are a deterministic, source-inspecting AI-assisted proxy audit by one Codex procedure, not human ratings.",
            "The two shuffled passes measure procedure repeatability, not independent inter-rater reliability.",
            "Pre-registered relevance terms simplify semantic relevance and can miss valid paraphrases or over-credit keyword matches.",
            "Confidence intervals resample the 28 synthetic profiles and do not model corpus, relevance-label, or reviewer uncertainty.",
            "Novelty, practical feasibility, data access, ethics approval, and supervisor suitability require external human/institutional confirmation.",
            "Results are bounded to 96 eligible papers and 719 eligible chunks in the recorded frozen corpus snapshot.",
        ],
        "artifact_files": {
            "raw_outputs": str(raw_outputs_path.relative_to(PROJECT_ROOT)),
            "review_pass_1": str(pass_one_path.relative_to(PROJECT_ROOT)),
            "review_pass_2": str(pass_two_path.relative_to(PROJECT_ROOT)),
            "weight_sensitivity": str(sensitivity_path.relative_to(PROJECT_ROOT)),
            "failures": str(failures_path.relative_to(PROJECT_ROOT)),
        },
    }
    write_json(aggregate_path, result)
    artifact_hashes = {
        path.name: sha256_file(path)
        for path in (raw_outputs_path, pass_one_path, pass_two_path, sensitivity_path, aggregate_path, failures_path)
    }
    manifest = {
        "evaluation_id": result["evaluation_id"],
        "completed_at": completed_at,
        "corpus_snapshot_hash": corpus["snapshot_hash"],
        "profiles_sha256": sha256_file(profiles_path),
        "review_prompt_sha256": sha256_file(prompt_path),
        "evaluation_code_sha256": sha256_file(module_path),
        "artifact_sha256": artifact_hashes,
    }
    write_json(output_dir / "manifest.json", manifest)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AI-assisted Thesis Extension Finder proxy evaluation.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_PATH)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dense-manifest", type=Path, default=DEFAULT_DENSE_MANIFEST_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        result = run_evaluation(
            session,
            profiles_path=args.profiles,
            schema_path=args.schema,
            prompt_path=args.prompt,
            output_dir=args.out_dir,
            dense_manifest_path=args.dense_manifest,
        )
    print(json.dumps({
        "status": result["status"],
        "profiles_completed": result["execution"]["profiles_completed"],
        "output": str(args.out_dir),
    }, indent=2))


if __name__ == "__main__":
    main()
