from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, desc, func, select

from app.db import create_db_and_tables, engine
from app.io_utils import atomic_write_json
from app.intelligence.artifact_verifier import verify_artifact_payload
from app.intelligence.podcast_script_generator import generate_podcast_script
from app.models import Chunk, Paper, PaperArtifact
from app.runtime_provenance import build_runtime_provenance

DEFAULT_PROVIDER = "offline_deterministic"
DEFAULT_MODEL = "paper-artifact-template-v1"
DEFAULT_OUTPUT_DIR = Path("data/generated/paper_artifacts")

SECTION_TYPES = [
    "public_summary",
    "technical_summary",
    "contribution",
    "methods",
    "limitations",
    "future_work",
    "possible_extensions",
    "required_skills",
    "evaluation_plan",
]
ARTIFACT_TYPES = set(SECTION_TYPES + ["podcast_script", "paper_intelligence_bundle"])
TEXT_ARTIFACT_TYPES = {
    "public_summary",
    "technical_summary",
    "contribution",
    "methods",
    "limitations",
    "future_work",
    "evaluation_plan",
}
CORRECTION_EVIDENCE_KEYS = {
    "citations",
    "citation",
    "source_chunk_ids",
    "source_chunk_ids_json",
    "source_basis",
    "cited_source_papers",
}

SECTION_PRIORITIES = {
    "abstract": 120,
    "introduction": 110,
    "background": 85,
    "method": 115,
    "methodology": 115,
    "approach": 105,
    "experiment": 95,
    "evaluation": 105,
    "result": 95,
    "discussion": 90,
    "limitation": 120,
    "future": 120,
    "conclusion": 105,
}

KEYWORD_PRIORITIES = {
    "contribution": 9,
    "propose": 8,
    "present": 7,
    "method": 8,
    "approach": 8,
    "result": 7,
    "limitation": 12,
    "future work": 12,
    "future research": 12,
    "evaluation": 9,
    "dataset": 7,
    "framework": 6,
    "system": 6,
}

LIMITATION_TERMS = ("limitation", "limitations", "constraint", "challenge", "challenges", "weakness")
FUTURE_TERMS = ("future work", "future research", "future", "extend", "extension", "improve", "next step")
METHOD_TERMS = ("method", "methodology", "approach", "algorithm", "model", "system", "framework", "architecture")
EVALUATION_TERMS = ("evaluation", "evaluate", "experiment", "metric", "accuracy", "precision", "recall", "result")


def utc_now() -> datetime:
    return datetime.now(UTC)


def generate_paper_artifacts(
    session: Session,
    paper_id: str,
    artifact_types: list[str] | None = None,
    *,
    provider: str = "auto",
    max_chunks: int = 12,
    overwrite: bool = False,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    requested_types = normalize_artifact_types(artifact_types)
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise ValueError(f"Paper not found: {paper_id}")

    chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.chunk_index)).all())
    provider_name, model_name, provider_warnings = resolve_provider(provider)
    if not chunks:
        response = insufficient_sources_response(paper, requested_types, provider_name, model_name, provider_warnings)
        persist_response(session, paper, response, requested_types, overwrite=overwrite)
        return response

    selected_chunks = select_source_chunks(chunks, max_chunks=max_chunks)
    source_pack = [source_entry(paper, chunk) for chunk in selected_chunks]
    bundle = build_intelligence_bundle(paper, source_pack)
    podcast = generate_podcast_script(bundle, source_pack)
    payloads = build_artifact_payloads(bundle, podcast)
    valid_chunk_ids = {chunk.chunk_id for chunk in chunks}

    response_artifacts: list[dict[str, Any]] = []
    response_warnings = list(provider_warnings)
    for artifact_type in requested_types:
        payload = payloads[artifact_type]
        verification = verify_artifact_payload(
            artifact_type,
            payload,
            valid_chunk_ids,
            paper,
            source_chunk_count=len(chunks),
        )
        record = upsert_artifact(
            session,
            paper,
            artifact_type,
            payload,
            provider=provider_name,
            model=model_name,
            grounding_status=verification["grounding_status"],
            warnings=verification["warnings"],
            overwrite=overwrite,
        )
        serialized = serialize_artifact(record)
        response_artifacts.append(serialized)
        response_warnings.extend(verification["warnings"])

    saved_json_path = save_artifacts_json(
        output_dir,
        paper,
        response_artifacts,
        response_warnings,
    )
    return {
        "paper_id": paper.paper_id,
        "paper_title": paper.title,
        "artifacts": response_artifacts,
        "grounding_status": combined_grounding_status(response_artifacts),
        "review_status": "needs_review",
        "citations": collect_artifact_citations(response_artifacts),
        "warnings": dedupe_preserve_order(response_warnings),
        "saved_json_path": str(saved_json_path),
    }


def normalize_artifact_types(artifact_types: list[str] | None) -> list[str]:
    values = artifact_types or ["paper_intelligence_bundle"]
    normalized = []
    for value in values:
        artifact_type = value.strip()
        if not artifact_type:
            continue
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"Unsupported artifact type: {artifact_type}")
        if artifact_type not in normalized:
            normalized.append(artifact_type)
    return normalized or ["paper_intelligence_bundle"]


def resolve_provider(provider_name: str) -> tuple[str, str, list[str]]:
    normalized = (provider_name or "auto").strip().lower()
    if normalized in {"auto", "offline", "offline_deterministic"}:
        return DEFAULT_PROVIDER, DEFAULT_MODEL, []
    return (
        DEFAULT_PROVIDER,
        DEFAULT_MODEL,
        [f"Provider '{provider_name}' is not implemented for Phase 6; used offline deterministic artifacts."],
    )


def insufficient_sources_response(
    paper: Paper,
    requested_types: list[str],
    provider: str,
    model: str,
    warnings: list[str],
) -> dict[str, Any]:
    artifacts = [
        {
            "artifact_id": str(uuid.uuid4()),
            "paper_id": paper.paper_id,
            "artifact_type": artifact_type,
            "generated_json": {},
            "generated_text": "",
            "source_chunk_ids": [],
            "citations": [],
            "provider": provider,
            "model": model,
            "generation_status": "insufficient_sources",
            "grounding_status": "unsupported",
            "review_status": "needs_review",
            "warnings": warnings + ["No source chunks are available for this paper."],
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
        for artifact_type in requested_types
    ]
    return {
        "paper_id": paper.paper_id,
        "paper_title": paper.title,
        "artifacts": artifacts,
        "grounding_status": "unsupported",
        "review_status": "needs_review",
        "citations": [],
        "warnings": warnings + ["No source chunks are available for this paper."],
        "saved_json_path": None,
    }


def persist_response(
    session: Session,
    paper: Paper,
    response: dict[str, Any],
    requested_types: list[str],
    *,
    overwrite: bool,
) -> None:
    for artifact in response["artifacts"]:
        upsert_artifact(
            session,
            paper,
            artifact["artifact_type"],
            artifact["generated_json"],
            provider=artifact["provider"],
            model=artifact["model"],
            generation_status=artifact["generation_status"],
            grounding_status=artifact["grounding_status"],
            warnings=artifact["warnings"],
            overwrite=overwrite,
        )


def select_source_chunks(chunks: list[Chunk], *, max_chunks: int) -> list[Chunk]:
    scored = sorted(
        chunks,
        key=lambda chunk: (chunk_score(chunk), -(chunk.chunk_index or 0)),
        reverse=True,
    )
    selected: list[Chunk] = []
    seen: set[str] = set()
    for chunk in scored:
        if chunk.chunk_id in seen:
            continue
        selected.append(chunk)
        seen.add(chunk.chunk_id)
        if len(selected) >= max_chunks:
            break
    if len(selected) < min(max_chunks, len(chunks)):
        for chunk in chunks:
            if chunk.chunk_id in seen:
                continue
            selected.append(chunk)
            seen.add(chunk.chunk_id)
            if len(selected) >= max_chunks:
                break
    return sorted(selected, key=lambda chunk: chunk.chunk_index)


def chunk_score(chunk: Chunk) -> int:
    section = (chunk.section or "").lower()
    text = chunk.text.lower()
    score = 0
    for key, value in SECTION_PRIORITIES.items():
        if key in section:
            score += value
    for key, value in KEYWORD_PRIORITIES.items():
        if key in text:
            score += value
    return score


def source_entry(paper: Paper, chunk: Chunk) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "text": clean_text(chunk.text),
        "snippet": trim_words(clean_text(chunk.text), 95),
    }


def build_intelligence_bundle(paper: Paper, source_pack: list[dict[str, Any]]) -> dict[str, Any]:
    intro_chunks = choose_chunks(source_pack, ["abstract", "introduction", "conclusion"], ("purpose", "propose", "present", "study"))
    method_chunks = choose_chunks(source_pack, ["method", "methodology", "approach", "system", "framework"], METHOD_TERMS)
    contribution_chunks = choose_chunks(source_pack, ["abstract", "introduction", "conclusion"], ("contribution", "propose", "present", "develop", "novel"))
    limitation_chunks, limitation_support = support_chunks(source_pack, LIMITATION_TERMS)
    future_chunks, future_support = support_chunks(source_pack, FUTURE_TERMS)
    evaluation_chunks = choose_chunks(source_pack, ["evaluation", "result", "discussion", "experiment"], EVALUATION_TERMS)

    summary_chunks = intro_chunks or source_pack[:2]
    method_basis = method_chunks or summary_chunks
    contribution_basis = contribution_chunks or summary_chunks
    evaluation_basis = evaluation_chunks or method_basis

    public_summary = section_payload(
        "AI-assisted unreviewed public summary: "
        + combine_sentences(summary_chunks, ("purpose", "propose", "present", "study", "system"), max_sentences=2),
        citations_for(summary_chunks),
    )
    technical_summary = section_payload(
        "AI-assisted unreviewed technical summary: "
        + combine_sentences(method_basis + evaluation_basis, METHOD_TERMS + EVALUATION_TERMS, max_sentences=3),
        citations_for((method_basis + evaluation_basis)[:3]),
    )
    contribution = section_payload(
        "AI-assisted unreviewed contribution: "
        + combine_sentences(contribution_basis, ("contribution", "propose", "present", "develop", "novel", "system"), max_sentences=2),
        citations_for(contribution_basis[:2]),
    )
    methods = section_payload(
        "AI-assisted unreviewed methods/approach: "
        + combine_sentences(method_basis, METHOD_TERMS, max_sentences=3),
        citations_for(method_basis[:3]),
    )
    limitations = support_payload(
        limitation_chunks,
        limitation_support,
        "limitations",
        fallback_text="No explicit limitations were found in the selected source chunks.",
    )
    future_work = support_payload(
        future_chunks,
        future_support,
        "future work",
        fallback_text="No explicit future-work statement was found in the selected source chunks.",
    )
    required_skills = {
        "skills": infer_required_skills(" ".join(chunk["text"] for chunk in method_basis + evaluation_basis)),
        "basis": "inferred from methods and implementation details",
        "citations": citations_for(method_basis[:3]),
    }
    evaluation_plan = build_evaluation_plan(evaluation_basis, method_basis)
    possible_extensions = build_possible_extensions(paper, summary_chunks, limitation_chunks, future_chunks, method_basis)

    return {
        "paper_id": paper.paper_id,
        "paper_title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "generated_notice": (
            "AI-assisted and unreviewed. Grounding status reports citation locators and weak lexical overlap; "
            "it does not establish entailment or factual correctness."
        ),
        "public_summary": public_summary,
        "technical_summary": technical_summary,
        "contribution": contribution,
        "methods": methods,
        "limitations": limitations,
        "future_work": future_work,
        "possible_extensions": possible_extensions,
        "required_skills": required_skills,
        "evaluation_plan": evaluation_plan,
        "warnings": [],
        "review_status": "needs_review",
    }


def build_artifact_payloads(bundle: dict[str, Any], podcast: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {"paper_intelligence_bundle": bundle, "podcast_script": podcast}
    for artifact_type in SECTION_TYPES:
        value = bundle[artifact_type]
        if artifact_type == "possible_extensions":
            payloads[artifact_type] = {
                "items": value,
                "support_status": "suggested_by_system",
                "citations": dedupe_citations([citation for item in value for citation in item.get("citations", [])]),
                "review_status": "needs_review",
            }
        else:
            payloads[artifact_type] = value
    return payloads


def choose_chunks(
    source_pack: list[dict[str, Any]],
    section_terms: list[str],
    text_terms: tuple[str, ...],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for chunk in source_pack:
        section = str(chunk.get("section") or "").lower()
        text = chunk["text"].lower()
        score = sum(12 for term in section_terms if term in section)
        score += sum(1 for term in text_terms if term in text)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (item[0], -int(item[1].get("chunk_index") or 0)), reverse=True)
    selected = [chunk for _score, chunk in scored[:limit]]
    return selected or source_pack[:limit]


def support_chunks(
    source_pack: list[dict[str, Any]],
    terms: tuple[str, ...],
    *,
    limit: int = 2,
) -> tuple[list[dict[str, Any]], str]:
    explicit: list[dict[str, Any]] = []
    inferred: list[dict[str, Any]] = []
    for chunk in source_pack:
        section = str(chunk.get("section") or "").lower()
        text = chunk["text"].lower()
        if any(term in section for term in terms) or any(term in text for term in terms):
            if any(term in section for term in terms[:2]) or any(term in text for term in terms[:2]):
                explicit.append(chunk)
            else:
                inferred.append(chunk)
    if explicit:
        return explicit[:limit], "explicit"
    if inferred:
        return inferred[:limit], "inferred"
    return [], "not_found"


def section_payload(text: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": text,
        "citations": citations,
    }


def support_payload(
    chunks: list[dict[str, Any]],
    support_status: str,
    label: str,
    *,
    fallback_text: str,
) -> dict[str, Any]:
    if support_status == "not_found":
        return {
            "text": fallback_text,
            "support_status": "not_found",
            "citations": [],
        }
    return {
        "text": "AI-assisted unreviewed {label}: {evidence}".format(
            label=label,
            evidence=combine_sentences(chunks, LIMITATION_TERMS + FUTURE_TERMS + EVALUATION_TERMS, max_sentences=2),
        ),
        "support_status": support_status,
        "citations": citations_for(chunks),
    }


def build_evaluation_plan(
    evaluation_chunks: list[dict[str, Any]],
    method_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    if evaluation_chunks:
        return {
            "text": "AI-assisted unreviewed evaluation plan: "
            + combine_sentences(evaluation_chunks, EVALUATION_TERMS, max_sentences=2),
            "basis": "explicit",
            "citations": citations_for(evaluation_chunks[:2]),
        }
    return {
        "text": "Suggested evaluation plan: define a small benchmark, compare against a baseline, report task-specific metrics, and review failure cases against the paper's methods.",
        "basis": "suggested_by_system",
        "citations": citations_for(method_chunks[:2]),
    }


def build_possible_extensions(
    paper: Paper,
    summary_chunks: list[dict[str, Any]],
    limitation_chunks: list[dict[str, Any]],
    future_chunks: list[dict[str, Any]],
    method_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    basis = future_chunks or limitation_chunks or method_chunks or summary_chunks
    title_stub = trim_words(paper.title, 8)
    return [
        {
            "title": f"Evaluation extension for {title_stub}",
            "summary": "Suggested by the system: create a small evaluation benchmark that tests the paper's approach on a new or more transparent sample.",
            "support_status": "suggested_by_system",
            "source_basis": [chunk["chunk_id"] for chunk in basis[:2]],
            "citations": citations_for(basis[:2]),
        },
        {
            "title": f"Public-facing prototype based on {title_stub}",
            "summary": "Suggested by the system: turn the paper's core idea into a narrow prototype or dashboard that makes the work easier for students or public users to inspect.",
            "support_status": "suggested_by_system",
            "source_basis": [chunk["chunk_id"] for chunk in (method_chunks or basis)[:2]],
            "citations": citations_for((method_chunks or basis)[:2]),
        },
    ]


def infer_required_skills(text: str) -> list[str]:
    lowered = text.lower()
    skills = ["research methods", "evaluation"]
    if any(term in lowered for term in ("python", "algorithm", "model", "machine learning", "classification")):
        skills.append("Python")
    if any(term in lowered for term in ("machine learning", "deep learning", "neural", "classification")):
        skills.append("machine learning")
    if any(term in lowered for term in ("retrieval", "rag", "language model", "llm")):
        skills.append("information retrieval")
    if any(term in lowered for term in ("web", "application", "dashboard", "interface")):
        skills.append("web application development")
    if any(term in lowered for term in ("optimization", "integer programming", "linear programming")):
        skills.append("optimization")
    if any(term in lowered for term in ("dataset", "data set", "data-driven", "statistics")):
        skills.append("data analysis")
    return dedupe_preserve_order(skills)


def combine_sentences(
    chunks: list[dict[str, Any]],
    preferred_terms: tuple[str, ...],
    *,
    max_sentences: int,
) -> str:
    selected: list[str] = []
    for chunk in chunks:
        sentences = split_sentences(chunk["text"])
        ranked = sorted(
            sentences,
            key=lambda sentence: sentence_score(sentence, preferred_terms),
            reverse=True,
        )
        for sentence in ranked[:2]:
            clean = trim_words(sentence, 48)
            if clean and clean not in selected:
                selected.append(clean)
            if len(selected) >= max_sentences:
                return " ".join(selected)
    if selected:
        return " ".join(selected)
    return "Insufficient readable source text was available for a strong draft."


def sentence_score(sentence: str, terms: tuple[str, ...]) -> int:
    lowered = sentence.lower()
    return sum(1 for term in terms if term in lowered)


def citations_for(chunks: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    return dedupe_citations([citation_from_source(chunk) for chunk in chunks[:limit]])


def citation_from_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": source["paper_id"],
        "title": source["title"],
        "chunk_id": source["chunk_id"],
        "section": source.get("section"),
        "page_start": source.get("page_start"),
        "page_end": source.get("page_end"),
        "snippet": source.get("snippet", ""),
    }


def upsert_artifact(
    session: Session,
    paper: Paper,
    artifact_type: str,
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    grounding_status: str,
    warnings: list[str],
    overwrite: bool,
    generation_status: str = "generated",
) -> PaperArtifact:
    existing = list(
        session.exec(
            select(PaperArtifact)
            .where(PaperArtifact.paper_id == paper.paper_id)
            .where(PaperArtifact.artifact_type == artifact_type)
            .order_by(desc(PaperArtifact.created_at))
        ).all()
    )
    if existing and not overwrite:
        return existing[0]
    # Overwrite means "create a newer draft", not "destroy the audit history".
    # Public selection resolves the latest approved version separately.
    now = utc_now()
    citations = collect_citations(payload)
    source_chunk_ids = sorted({citation["chunk_id"] for citation in citations if citation.get("chunk_id")})
    runtime_provenance = build_runtime_provenance(
        session,
        record_type="paper_artifact",
        generation_config={
            "artifact_type": artifact_type,
            "generation_status": generation_status,
            "grounding_contract": "structural_support_unverified_v1",
            "template_model": model,
        },
        provider=provider,
        model=model,
        generated_at=now,
        retrieval_mode=None,
        source_chunk_ids=source_chunk_ids,
        corpus_scope="technical",
    )
    artifact = PaperArtifact(
        artifact_id=str(uuid.uuid4()),
        paper_id=paper.paper_id,
        artifact_type=artifact_type,
        generated_json=payload,
        generated_text=extract_generated_text(payload),
        source_chunk_ids_json=source_chunk_ids,
        citations_json=citations,
        provider=provider,
        model=model,
        generation_status=generation_status,
        grounding_status=grounding_status,
        review_status="needs_review",
        warnings_json=dedupe_preserve_order(warnings),
        runtime_provenance_json=runtime_provenance,
        created_at=now,
        updated_at=now,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


def serialize_artifact(artifact: PaperArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "paper_id": artifact.paper_id,
        "artifact_type": artifact.artifact_type,
        "generated_json": artifact.generated_json,
        "generated_text": artifact.generated_text,
        "source_chunk_ids": artifact.source_chunk_ids_json,
        "citations": artifact.citations_json,
        "provider": artifact.provider,
        "model": artifact.model,
        "generation_status": artifact.generation_status,
        "grounding_status": artifact.grounding_status,
        "review_status": artifact.review_status,
        "reviewer_notes": artifact.reviewer_notes,
        "reviewed_at": artifact.reviewed_at.isoformat() if artifact.reviewed_at else None,
        "reviewed_by": artifact.reviewed_by,
        "corrected_text": artifact.corrected_text,
        "corrected_json": artifact.corrected_json,
        "correction_grounding_status": artifact.correction_grounding_status,
        "correction_source_chunk_ids": artifact.correction_source_chunk_ids_json,
        "correction_citations": artifact.correction_citations_json,
        "correction_runtime_provenance": artifact.correction_runtime_provenance_json,
        "warnings": artifact.warnings_json,
        "runtime_provenance": artifact.runtime_provenance_json,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }


def serialize_public_artifact(artifact: PaperArtifact) -> dict[str, Any]:
    """Serialize an artifact without exposing protected review workspace data.

    Review notes and stable reviewer identifiers are administrative data. Draft
    corrections are also private until a human administrator has approved the
    corrected artifact. The public payload retains the review status and
    timestamp so clients can communicate provenance without identifying the
    reviewer or disclosing work in progress.
    """

    if artifact.review_status != "approved":
        raise ValueError("Only approved artifacts may be serialized for public output")
    correction_blockers = artifact_correction_blockers(artifact)
    if correction_blockers:
        raise ValueError(f"Artifact correction is not publishable: {', '.join(correction_blockers)}")
    corrected_json = artifact.corrected_json if isinstance(artifact.corrected_json, dict) else {}
    use_corrected_json = bool(corrected_json)
    correction_used = use_corrected_json
    effective_source_chunk_ids = (
        artifact.correction_source_chunk_ids_json if correction_used else artifact.source_chunk_ids_json
    )
    effective_citations = artifact.correction_citations_json if correction_used else artifact.citations_json
    effective_grounding = artifact.correction_grounding_status if correction_used else artifact.grounding_status
    effective_warnings = list(artifact.warnings_json or [])
    if correction_used and artifact.correction_grounding_status != "grounded":
        effective_warnings = dedupe_preserve_order(
            [
                *effective_warnings,
                "Reviewer-corrected content has not been reverified against source chunks; original generated evidence was not inherited.",
            ]
        )
    return {
        "artifact_id": artifact.artifact_id,
        "paper_id": artifact.paper_id,
        "artifact_type": artifact.artifact_type,
        "effective_json": corrected_json if use_corrected_json else artifact.generated_json,
        "effective_text": extract_generated_text(corrected_json) if correction_used else artifact.generated_text,
        "source_chunk_ids": effective_source_chunk_ids,
        "citations": effective_citations,
        "generation_status": artifact.generation_status,
        "grounding_status": effective_grounding,
        "review_status": artifact.review_status,
        "reviewed_at": artifact.reviewed_at.isoformat() if artifact.reviewed_at else None,
        "warnings": effective_warnings,
        "provenance": {
            "source": "reviewer_correction" if correction_used else "generated",
            "provider": None if correction_used else artifact.provider,
            "model": None if correction_used else artifact.model,
            "generated_at": None if correction_used else artifact.created_at.isoformat(),
            "approved_version": "corrected" if correction_used else "generated",
            "correction_fields": ["json"] if correction_used else [],
            "derived_fields": ["text"] if correction_used else [],
            "runtime": (
                artifact.correction_runtime_provenance_json
                if correction_used
                else artifact.runtime_provenance_json
            ),
            "evidence_verification": "not_performed" if correction_used else "generation_time_structural_check",
            "original_generated_evidence_inherited": False if correction_used else None,
        },
    }


def strip_nested_correction_evidence(value: Any) -> Any:
    """Remove inherited or reviewer-supplied evidence locators recursively.

    A correction is new authored content. It cannot inherit citations from the
    generated draft merely because the surrounding JSON shape was copied. A
    future re-verification workflow may add correction-specific evidence, but
    the current conservative contract strips it and records the correction as
    unsupported.
    """

    if isinstance(value, dict):
        return {
            key: strip_nested_correction_evidence(child)
            for key, child in value.items()
            if key not in CORRECTION_EVIDENCE_KEYS
        }
    if isinstance(value, list):
        return [strip_nested_correction_evidence(child) for child in value]
    return value


def canonicalize_artifact_correction(
    artifact: PaperArtifact,
    *,
    corrected_json: dict[str, Any] | None,
    corrected_text: str | None,
) -> tuple[dict[str, Any], str]:
    """Return one type-checked JSON authority and its derived text mirror."""

    if corrected_json is None:
        if artifact.artifact_type not in TEXT_ARTIFACT_TYPES:
            raise ValueError(f"{artifact.artifact_type} corrections require structured JSON")
        if corrected_text is None:
            raise ValueError("A correction value is required")
        source = artifact.corrected_json if isinstance(artifact.corrected_json, dict) and artifact.corrected_json else artifact.generated_json
        payload = dict(source or {})
        payload["text"] = corrected_text
    else:
        payload = dict(corrected_json)

    canonical = strip_nested_correction_evidence(payload)
    if not isinstance(canonical, dict):  # pragma: no cover - dict input is enforced above
        raise ValueError("Artifact correction must be a JSON object")
    validate_canonical_artifact_payload(artifact.artifact_type, canonical, paper_id=artifact.paper_id)
    canonical = normalize_canonical_artifact_payload(artifact.artifact_type, canonical)
    derived_text = extract_generated_text(canonical)
    if corrected_text is not None and corrected_text != derived_text:
        raise ValueError("corrected_text must exactly match the text derived from corrected_json")
    return canonical, derived_text


def normalize_canonical_artifact_payload(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Project a validated correction onto its one supported public shape."""

    if artifact_type in TEXT_ARTIFACT_TYPES:
        result: dict[str, Any] = {"text": payload["text"], "citations": []}
        for key in ("support_status", "basis"):
            if isinstance(payload.get(key), str) and payload[key].strip():
                result[key] = payload[key]
        return result
    if artifact_type == "required_skills":
        result = {
            "skills": dedupe_preserve_order([item.strip() for item in payload["skills"]]),
            "citations": [],
        }
        if isinstance(payload.get("basis"), str) and payload["basis"].strip():
            result["basis"] = payload["basis"]
        return result
    if artifact_type == "possible_extensions":
        return {
            "items": [_canonical_extension_item(item) for item in payload["items"]],
            "citations": [],
            "review_status": "needs_review",
        }
    if artifact_type == "podcast_script":
        script = [
            {"speaker": turn["speaker"].strip(), "text": turn["text"].strip()}
            for turn in payload["script"]
        ]
        speakers = payload.get("speakers")
        normalized_speakers = (
            dedupe_preserve_order([item.strip() for item in speakers if isinstance(item, str) and item.strip()])
            if isinstance(speakers, list)
            else dedupe_preserve_order([turn["speaker"] for turn in script])
        )
        return {
            "episode_title": payload["episode_title"].strip(),
            "short_description": str(payload.get("short_description") or "").strip(),
            "audience": str(payload.get("audience") or "general public").strip(),
            "duration_target": "3-5 minutes",
            "speakers": normalized_speakers,
            "script": script,
            "cited_source_papers": [],
            "citations": [],
            "warnings": _string_list(payload.get("warnings")),
            "review_status": "needs_review",
        }
    if artifact_type == "paper_intelligence_bundle":
        return {
            "paper_id": payload["paper_id"],
            "paper_title": payload["paper_title"].strip(),
            "authors": _string_list(payload.get("authors")),
            "year": payload.get("year"),
            "generated_notice": str(payload.get("generated_notice") or "Reviewer-corrected content; source support has not been reverified.").strip(),
            "public_summary": normalize_canonical_artifact_payload("public_summary", payload["public_summary"]),
            "technical_summary": normalize_canonical_artifact_payload("technical_summary", payload["technical_summary"]),
            "contribution": normalize_canonical_artifact_payload("contribution", payload["contribution"]),
            "methods": normalize_canonical_artifact_payload("methods", payload["methods"]),
            "limitations": normalize_canonical_artifact_payload("limitations", payload["limitations"]),
            "future_work": normalize_canonical_artifact_payload("future_work", payload["future_work"]),
            "possible_extensions": [_canonical_extension_item(item) for item in payload["possible_extensions"]],
            "required_skills": normalize_canonical_artifact_payload("required_skills", payload["required_skills"]),
            "evaluation_plan": normalize_canonical_artifact_payload("evaluation_plan", payload["evaluation_plan"]),
            "warnings": _string_list(payload.get("warnings")),
            "review_status": "needs_review",
        }
    raise ValueError(f"Unsupported artifact correction type: {artifact_type}")


def _canonical_extension_item(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": item["title"].strip(),
        "summary": item["summary"].strip(),
        "citations": [],
    }
    if isinstance(item.get("support_status"), str) and item["support_status"].strip():
        result["support_status"] = item["support_status"]
    else:
        result["support_status"] = "suggested_extension"
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return dedupe_preserve_order([item.strip() for item in value if isinstance(item, str) and item.strip()])


def validate_canonical_artifact_payload(
    artifact_type: str,
    payload: dict[str, Any],
    *,
    paper_id: str | None = None,
) -> None:
    """Validate the minimum type-specific public rendering contract."""

    if artifact_type in TEXT_ARTIFACT_TYPES:
        _require_nonempty_text(payload, "text", f"{artifact_type} correction")
        return
    if artifact_type == "required_skills":
        skills = payload.get("skills")
        if not isinstance(skills, list) or not skills or any(not isinstance(item, str) or not item.strip() for item in skills):
            raise ValueError("required_skills correction requires a non-empty skills list")
        return
    if artifact_type == "possible_extensions":
        _validate_extension_items(payload.get("items"))
        return
    if artifact_type == "podcast_script":
        _require_nonempty_text(payload, "episode_title", "Podcast correction")
        script = payload.get("script")
        if not isinstance(script, list) or not script:
            raise ValueError("Podcast correction requires a non-empty script")
        for turn in script:
            if not isinstance(turn, dict):
                raise ValueError("Each podcast script turn requires speaker and text")
            _require_nonempty_text(turn, "speaker", "Podcast script turn")
            _require_nonempty_text(turn, "text", "Podcast script turn")
        return
    if artifact_type == "paper_intelligence_bundle":
        if paper_id is not None and payload.get("paper_id") != paper_id:
            raise ValueError("Paper intelligence correction paper_id does not match its artifact")
        _require_nonempty_text(payload, "paper_title", "Paper intelligence correction")
        for section in (
            "public_summary",
            "technical_summary",
            "contribution",
            "methods",
            "limitations",
            "future_work",
            "evaluation_plan",
        ):
            value = payload.get(section)
            if not isinstance(value, dict):
                raise ValueError(f"Paper intelligence correction requires object section '{section}'")
            _require_nonempty_text(value, "text", f"Paper intelligence section '{section}'")
        skills = payload.get("required_skills")
        if not isinstance(skills, dict):
            raise ValueError("Paper intelligence correction requires required_skills")
        validate_canonical_artifact_payload("required_skills", skills)
        _validate_extension_items(payload.get("possible_extensions"))
        return
    raise ValueError(f"Unsupported artifact correction type: {artifact_type}")


def _require_nonempty_text(payload: dict[str, Any], key: str, label: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} requires non-empty {key}")


def _validate_extension_items(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("possible_extensions correction requires non-empty items")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each corrected extension requires title and summary")
        _require_nonempty_text(item, "title", "Corrected extension")
        _require_nonempty_text(item, "summary", "Corrected extension")


def artifact_correction_blockers(artifact: PaperArtifact) -> list[str]:
    """Describe why an existing correction cannot be approved or delivered."""

    corrected_json = artifact.corrected_json if isinstance(artifact.corrected_json, dict) else {}
    correction_used = bool(corrected_json) or artifact.corrected_text is not None
    if not correction_used:
        return []
    blockers: list[str] = []
    if not corrected_json:
        blockers.append("correction_json_missing")
        return blockers
    try:
        canonical, derived_text = canonicalize_artifact_correction(
            artifact,
            corrected_json=corrected_json,
            corrected_text=artifact.corrected_text,
        )
    except ValueError:
        blockers.append("correction_payload_invalid_or_text_mismatch")
        return blockers
    if canonical != corrected_json:
        blockers.append("correction_contains_unverified_evidence")
    if artifact.corrected_text != derived_text:
        blockers.append("correction_text_json_mismatch")
    if artifact.correction_source_chunk_ids_json or artifact.correction_citations_json:
        blockers.append("correction_evidence_not_reverified")
    if artifact.correction_grounding_status != "unsupported":
        blockers.append("correction_grounding_status_inconsistent")
    return blockers


def save_artifacts_json(
    output_dir: Path,
    paper: Paper,
    artifacts: list[dict[str, Any]],
    warnings: list[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{paper.paper_id}.json"
    payload = {
        "paper_id": paper.paper_id,
        "paper_title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "review_status": "needs_review",
        "warnings": dedupe_preserve_order(warnings),
        "artifacts": artifacts,
    }
    atomic_write_json(output_path, payload)
    return output_path


def collect_artifact_citations(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_citations([citation for artifact in artifacts for citation in artifact.get("citations", [])])


def collect_citations(payload: Any) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if set(["paper_id", "title", "chunk_id"]).issubset(payload):
            citations.append(payload)
        for value in payload.values():
            citations.extend(collect_citations(value))
    elif isinstance(payload, list):
        for item in payload:
            citations.extend(collect_citations(item))
    return dedupe_citations(citations)


def dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(citation)
    return deduped


def extract_generated_text(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"]
        if isinstance(payload.get("script"), list):
            return "\n".join(f"{line.get('speaker')}: {line.get('text')}" for line in payload["script"])
        if "public_summary" in payload:
            return payload["public_summary"].get("text", "")
        if "items" in payload:
            return "\n".join(item.get("summary", "") for item in payload["items"])
    return ""


def combined_grounding_status(artifacts: list[dict[str, Any]]) -> str:
    statuses = [artifact["grounding_status"] for artifact in artifacts]
    if not statuses or all(status == "unsupported" for status in statuses):
        return "unsupported"
    if any(status in {"partial", "unsupported"} for status in statuses):
        return "partial"
    return "grounded"


def artifact_diagnostics(session: Session) -> dict[str, Any]:
    artifacts = list(session.exec(select(PaperArtifact)).all())
    papers_with_artifacts = {
        artifact.paper_id
        for artifact in artifacts
        if artifact.generation_status == "generated"
    }
    by_type: dict[str, int] = {}
    for artifact in artifacts:
        by_type[artifact.artifact_type] = by_type.get(artifact.artifact_type, 0) + 1
    return {
        "total_papers": session.exec(select(func.count()).select_from(Paper)).one(),
        "papers_with_artifacts": len(papers_with_artifacts),
        "total_artifacts": len(artifacts),
        "artifacts_by_type": dict(sorted(by_type.items())),
        "grounded_artifacts": sum(1 for artifact in artifacts if artifact.grounding_status == "grounded"),
        "partial_artifacts": sum(1 for artifact in artifacts if artifact.grounding_status == "partial"),
        "unsupported_artifacts": sum(1 for artifact in artifacts if artifact.grounding_status == "unsupported"),
        "needs_review_count": sum(1 for artifact in artifacts if artifact.review_status == "needs_review"),
        "failed_generation_count": sum(1 for artifact in artifacts if artifact.generation_status == "failed"),
        "default_provider": DEFAULT_PROVIDER,
    }


def batch_generate_paper_artifacts(
    session: Session,
    *,
    paper_ids: list[str] | None = None,
    limit: int = 5,
    artifact_types: list[str] | None = None,
    provider: str = "auto",
    max_chunks: int = 12,
    overwrite: bool = False,
) -> dict[str, Any]:
    requested_ids = [paper_id for paper_id in (paper_ids or []) if paper_id]
    if requested_ids:
        papers = [paper for paper_id in requested_ids if (paper := session.get(Paper, paper_id)) is not None]
    else:
        chunked_paper_ids = list(
            session.exec(select(Chunk.paper_id).group_by(Chunk.paper_id).limit(limit)).all()
        )
        papers = [paper for paper_id in chunked_paper_ids if (paper := session.get(Paper, paper_id)) is not None]
    papers = papers[: max(limit, 0)]
    results = [
        generate_paper_artifacts(
            session,
            paper.paper_id,
            artifact_types,
            provider=provider,
            max_chunks=max_chunks,
            overwrite=overwrite,
        )
        for paper in papers
    ]
    return {
        "requested_limit": limit,
        "processed": len(results),
        "results": results,
    }


def list_paper_artifacts(
    session: Session,
    paper_id: str,
    *,
    public: bool = False,
) -> list[dict[str, Any]]:
    statement = (
        select(PaperArtifact)
        .where(PaperArtifact.paper_id == paper_id)
        .order_by(PaperArtifact.artifact_type, desc(PaperArtifact.created_at))
    )
    if public:
        statement = statement.where(PaperArtifact.review_status == "approved")
    records = session.exec(statement).all()
    serializer = serialize_public_artifact if public else serialize_artifact
    serialized: list[dict[str, Any]] = []
    for record in records:
        try:
            serialized.append(serializer(record))
        except ValueError:
            if not public:
                raise
            # A legacy or externally modified approved correction is withheld
            # rather than becoming a public 500 response or inconsistent view.
            continue
    return serialized


def get_latest_paper_artifact(
    session: Session,
    paper_id: str,
    artifact_type: str,
    *,
    public: bool = False,
) -> dict[str, Any] | None:
    statement = (
        select(PaperArtifact)
        .where(PaperArtifact.paper_id == paper_id)
        .where(PaperArtifact.artifact_type == artifact_type)
        .order_by(desc(PaperArtifact.created_at))
    )
    if public:
        statement = statement.where(PaperArtifact.review_status == "approved")
    records = list(session.exec(statement).all())
    for record in records:
        try:
            return serialize_public_artifact(record) if public else serialize_artifact(record)
        except ValueError:
            if not public:
                raise
            continue
    return None


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", normalized) if part.strip()]


def trim_words(text: str, max_words: int) -> str:
    words = clean_text(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


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
    parser = argparse.ArgumentParser(description="Generate source-cited paper intelligence artifacts.")
    subparsers = parser.add_subparsers(dest="command")
    generate = subparsers.add_parser("generate")
    generate.add_argument("--paper-id", required=True)
    generate.add_argument("--types", nargs="+", default=["paper_intelligence_bundle", "podcast_script"])
    generate.add_argument("--provider", default="auto")
    generate.add_argument("--max-chunks", type=int, default=12)
    generate.add_argument("--overwrite", action="store_true")

    batch = subparsers.add_parser("batch")
    batch.add_argument("--paper-ids", nargs="*", default=[])
    batch.add_argument("--limit", type=int, default=5)
    batch.add_argument("--types", nargs="+", default=["paper_intelligence_bundle", "podcast_script"])
    batch.add_argument("--provider", default="auto")
    batch.add_argument("--max-chunks", type=int, default=12)
    batch.add_argument("--overwrite", action="store_true")

    show = subparsers.add_parser("show")
    show.add_argument("--paper-id", required=True)
    return parser


def print_generation_result(response: dict[str, Any]) -> None:
    print(f"paper_id: {response['paper_id']}")
    print(f"grounding_status: {response['grounding_status']}")
    print(f"review_status: {response['review_status']}")
    print(f"saved_json_path: {response.get('saved_json_path')}")
    print("artifacts:")
    for artifact in response["artifacts"]:
        print(
            f"- {artifact['artifact_type']} status={artifact['generation_status']} "
            f"grounding={artifact['grounding_status']} citations={len(artifact['citations'])}"
        )
    if response["warnings"]:
        print("warnings:")
        for warning in response["warnings"]:
            print(f"- {warning}")


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        if args.command == "generate":
            response = generate_paper_artifacts(
                session,
                args.paper_id,
                args.types,
                provider=args.provider,
                max_chunks=args.max_chunks,
                overwrite=args.overwrite,
            )
            print_generation_result(response)
            return
        if args.command == "batch":
            response = batch_generate_paper_artifacts(
                session,
                paper_ids=args.paper_ids,
                limit=args.limit,
                artifact_types=args.types,
                provider=args.provider,
                max_chunks=args.max_chunks,
                overwrite=args.overwrite,
            )
            print(f"processed={response['processed']} requested_limit={response['requested_limit']}")
            for result in response["results"]:
                print_generation_result(result)
            return
        if args.command == "show":
            artifacts = list_paper_artifacts(session, args.paper_id)
            print(json.dumps(artifacts, indent=2))
            return
    build_parser().print_help()


if __name__ == "__main__":
    main()
