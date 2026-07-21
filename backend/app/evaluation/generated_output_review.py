"""Evidence-linked, idempotent AI review of every stored generated output.

This module does not grant human approval.  It records ``ai_reviewed`` only
when deterministic source, schema, and safety checks pass; otherwise it records
``needs_reprocess``.  The CLI proves the operation twice on a SQLite backup
before an optional live apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import inspect
from sqlmodel import Session, create_engine, desc, select

from app.api.admin import verify_review_event_chain
from app.intelligence.artifact_verifier import collect_cited_chunk_ids, verify_artifact_payload
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.extension_recommender import ExtensionFinderRequest, recommend_extensions
from app.intelligence.paper_artifact_generator import (
    build_artifact_payloads,
    build_intelligence_bundle,
    collect_citations as collect_artifact_citations,
    extract_generated_text,
    select_source_chunks,
    source_entry,
)
from app.intelligence.podcast_script_generator import generate_podcast_script
from app.intelligence.recommendation_verifier import verify_recommendations
from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = ROOT / "data/papers.db"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts/phase4/generated_output_review"
REVIEW_VERSION = "phase4-generated-output-review-v1"
REVIEWER_ID = "codex-ai-review"
REVIEWER_NAME = "Codex AI Review"
REVIEWER_TYPE = "ai"
REVIEWER_ROLE = "reviewer"
REVIEW_REQUEST_ID = REVIEW_VERSION
AI_REVIEW_NOTICE = (
    "AI-reviewed for source locators, output structure, and explicit suggestion boundaries; "
    "not human-approved, author-validated, or supervisor-endorsed."
)

ARTIFACT_REQUIRED_BUNDLE_FIELDS = {
    "public_summary",
    "technical_summary",
    "contribution",
    "methods",
    "limitations",
    "future_work",
    "possible_extensions",
    "required_skills",
    "evaluation_plan",
}

RECOMMENDATION_REQUIRED_FIELDS = {
    "paper_id",
    "paper_focus",
    "source_supported_facts",
    "identified_gap",
    "extension_summary",
    "mvp_scope",
    "stretch_goals",
    "required_skills",
    "data_required",
    "data_availability",
    "evaluation_plan",
    "difficulty",
    "risk_level",
    "implementation_time",
    "citations",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(child) for child in value]
    return value


def dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


@dataclass
class ReviewDecision:
    item_type: str
    item_id: str
    target_status: str
    rationale: str
    content_sha256: str
    checks: dict[str, Any]
    evidence: list[dict[str, Any]]
    corrections: list[dict[str, Any]] = field(default_factory=list)

    def sanitized(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["corrections"] = [sanitized_correction(correction) for correction in self.corrections]
        payload.update(
            {
                "review_version": REVIEW_VERSION,
                "reviewer_id": REVIEWER_ID,
                "reviewer_type": REVIEWER_TYPE,
                "human_validation": False,
                "review_notice": AI_REVIEW_NOTICE,
            }
        )
        return payload


def sanitized_correction(correction: dict[str, Any]) -> dict[str, Any]:
    return {
        "field": correction["field"],
        "before_sha256": correction.get("before_sha256") or sha256_value(correction.get("before")),
        "after_sha256": correction.get("after_sha256") or sha256_value(correction.get("after")),
        "reason": correction.get("reason"),
    }


def compatibility_report(database_engine: Any) -> dict[str, Any]:
    inspector = inspect(database_engine)
    required = {
        "raganswer": {"review_status", "reviewer_notes", "reviewed_at", "reviewed_by"},
        "thesisrecommendation": {"review_status", "reviewer_notes", "reviewed_at", "reviewed_by"},
        "paperartifact": {"review_status", "reviewer_notes", "reviewed_at", "reviewed_by"},
        "reviewevent": {
            "reviewer_id",
            "reviewer_type",
            "reviewer_role",
            "request_id",
            "previous_event_hash",
            "event_hash",
            "diff_json",
        },
    }
    missing: dict[str, list[str]] = {}
    existing_tables = set(inspector.get_table_names())
    for table, columns in required.items():
        if table not in existing_tables:
            missing[table] = sorted(columns)
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        absent = sorted(columns - present)
        if absent:
            missing[table] = absent
    if missing:
        raise RuntimeError(f"Generated-output review schema is not migrated: {missing}")
    return {
        "status": "compatible",
        "migration_required": False,
        "review_status": "ai_reviewed is stored as a distinct string state",
        "append_only_review_events": database_engine.dialect.name == "sqlite",
    }


def normalize_source_text(value: str) -> str:
    value = value.replace("[[", "").replace("]]", "")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def collect_nested_citations(value: Any) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("chunk_id") and value.get("paper_id"):
            citations.append(value)
        for child in value.values():
            citations.extend(collect_nested_citations(child))
    elif isinstance(value, list):
        for child in value:
            citations.extend(collect_nested_citations(child))
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for citation in citations:
        key = (str(citation.get("paper_id") or ""), str(citation.get("chunk_id") or ""))
        if key not in seen:
            seen.add(key)
            result.append(citation)
    return result


def audit_citations(
    session: Session,
    citations: list[dict[str, Any]],
    *,
    expected_paper_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        paper_id = str(citation.get("paper_id") or "")
        chunk = session.get(Chunk, chunk_id) if chunk_id else None
        paper = session.get(Paper, paper_id) if paper_id else None
        locator_errors: list[str] = []
        if chunk is None:
            locator_errors.append("missing_chunk")
        if paper is None:
            locator_errors.append("missing_paper")
        if chunk is not None and chunk.paper_id != paper_id:
            locator_errors.append("chunk_paper_mismatch")
        if expected_paper_id and paper_id != expected_paper_id:
            locator_errors.append("unexpected_paper")
        if paper is not None and paper.corpus_eligibility_status != "eligible":
            locator_errors.append("ineligible_or_excluded_paper")
        if paper is not None and citation.get("title") and citation.get("title") != paper.title:
            locator_errors.append("title_mismatch")
        if chunk is not None:
            if citation.get("page_start") is not None and citation.get("page_start") != chunk.page_start:
                locator_errors.append("page_start_mismatch")
            if citation.get("page_end") is not None and citation.get("page_end") != chunk.page_end:
                locator_errors.append("page_end_mismatch")
            citation_text = normalize_source_text(str(citation.get("snippet") or ""))
            chunk_text = normalize_source_text(chunk.text)
            if citation_text and citation_text[:120] not in chunk_text:
                warnings.append(f"citation_snippet_not_exact:{chunk_id}")
        errors.extend(f"{error}:{chunk_id or 'missing'}" for error in locator_errors)
        evidence.append(
            {
                "paper_id": paper_id,
                "chunk_id": chunk_id,
                "page_start": chunk.page_start if chunk else citation.get("page_start"),
                "page_end": chunk.page_end if chunk else citation.get("page_end"),
                "section": chunk.section if chunk else citation.get("section"),
                "source_hash": chunk.source_hash if chunk else None,
                "citation_snippet_sha256": sha256_value(str(citation.get("snippet") or "")),
                "locator_status": "valid" if not locator_errors else "invalid",
                "locator_errors": locator_errors,
            }
        )
    return evidence, dedupe(errors), dedupe(warnings)


def corrected_field(record: Any, field_name: str, after: Any) -> dict[str, Any] | None:
    before = getattr(record, field_name)
    if before == after:
        return None
    return {
        "field": field_name,
        "before": before,
        "after": after,
        "before_sha256": sha256_value(before),
        "after_sha256": sha256_value(after),
        "reason": "Deterministic regeneration or verification metadata correction.",
    }


def review_answer(session: Session, answer: RAGAnswer) -> ReviewDecision:
    citations = list(answer.citations_json or [])
    evidence, locator_errors, locator_warnings = audit_citations(session, citations)
    retrieved_ids = set(answer.retrieved_chunk_ids or [])
    cited_ids = {str(item.get("chunk_id") or "") for item in citations}
    cited_papers = {str(item.get("paper_id") or "") for item in citations}
    structural_errors = list(locator_errors)
    if cited_ids.difference(retrieved_ids):
        structural_errors.append("citation_not_in_retrieved_ids")
    if cited_papers != set(answer.cited_paper_ids or []):
        structural_errors.append("cited_paper_id_summary_mismatch")
    stored_retrieved = list(answer.retrieved_chunks_json or [])
    verification = verify_citations(answer.answer, stored_retrieved, citations)
    quality_errors: list[str] = []
    text = " ".join(answer.answer.split())
    if not text:
        quality_errors.append("empty_answer")
    if "[[" in answer.answer or "]]" in answer.answer:
        quality_errors.append("search_highlight_markup_leaked_into_answer")
    if text.startswith("Based on the indexed TTLAB paper chunks,"):
        quality_errors.append("raw_extractive_fragment_concatenation")
    abstention = "do not contain enough evidence" in text.casefold()
    subjective_question = bool(re.search(r"\b(crap|good|bad|quality opinion)\b", answer.question.casefold()))
    if abstention and not subjective_question:
        quality_errors.append("unsupported_abstention_despite_stored_retrieval")
    if "only the first paper" in text.casefold() and "other papers" in text.casefold():
        quality_errors.append("internally_contradictory_scope_statement")
    if len(text.split()) > 300:
        quality_errors.append("answer_exceeds_review_bound")
    if verification["grounding_status"] != "grounded" and not (abstention and subjective_question):
        structural_errors.append(f"citation_verifier_{verification['grounding_status']}")
    target = "needs_reprocess" if structural_errors or quality_errors else "ai_reviewed"
    corrections: list[dict[str, Any]] = []
    verified_grounding = "unsupported" if locator_errors else verification["grounding_status"]
    review_warnings = list(answer.warnings_json or []) + locator_warnings + verification["warnings"]
    if locator_errors:
        review_warnings.append(
            "Stored citation locators no longer resolve against the frozen corpus; regenerate before use."
        )
    for correction in (
        corrected_field(answer, "grounding_status", verified_grounding),
        corrected_field(answer, "warnings_json", dedupe(review_warnings)),
        corrected_field(answer, "unsupported_claims_json", dedupe(list(answer.unsupported_claims_json or []) + verification["unsupported_claims"])),
    ):
        if correction:
            corrections.append(correction)
    if target == "ai_reviewed":
        rationale = (
            "AI source/structure review found valid eligible-corpus citation locators and no deterministic malformed-output flags. "
            "This is not a human judgment of usefulness or complete entailment."
        )
    else:
        rationale = "AI review requires reprocessing: " + "; ".join(dedupe(structural_errors + quality_errors)) + "."
    return ReviewDecision(
        item_type="rag_answer",
        item_id=answer.answer_id,
        target_status=target,
        rationale=rationale,
        content_sha256=sha256_value({"question": answer.question, "answer": answer.answer, "citations": citations}),
        checks={
            "citation_locator_errors": structural_errors,
            "citation_locator_warnings": locator_warnings,
            "quality_errors": quality_errors,
            "citation_verifier_status": verification["grounding_status"],
            "current_corpus_grounding_status": verified_grounding,
            "regeneration_attempted": False,
            "regeneration_reason": "Original request omitted paper scope, audience, and max-word generation parameters.",
            "citation_count": len(citations),
            "retrieved_chunk_count": len(retrieved_ids),
            "subjective_abstention": abstention and subjective_question,
        },
        evidence=evidence,
        corrections=corrections,
    )


def review_recommendation(session: Session, record: ThesisRecommendation) -> ReviewDecision:
    regeneration_error: str | None = None
    fresh_response: dict[str, Any] | None = None
    try:
        request = ExtensionFinderRequest.model_validate(record.request_json)
        fresh_response = recommend_extensions(
            session,
            request,
            persist=False,
            retrieval_scope="technical",
        )
        recommendations = list(fresh_response["recommendations"] or [])
    except Exception as exc:  # fail closed while retaining the original output for audit
        regeneration_error = f"{type(exc).__name__}: {exc}"
        recommendations = list(record.recommendations_json or [])
    citations = collect_nested_citations(recommendations)
    evidence, locator_errors, locator_warnings = audit_citations(session, citations)
    schema_errors: list[str] = []
    if regeneration_error:
        schema_errors.append("deterministic_regeneration_failed")
    if not recommendations:
        schema_errors.append("no_recommendations")
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        chunk = session.get(Chunk, item["chunk_id"]) if item["chunk_id"] else None
        if chunk:
            chunks_by_id[chunk.chunk_id] = {"chunk_id": chunk.chunk_id, "paper_id": chunk.paper_id, "text": chunk.text}
    for index, recommendation in enumerate(recommendations, start=1):
        missing = sorted(RECOMMENDATION_REQUIRED_FIELDS - set(recommendation))
        if missing:
            schema_errors.append(f"recommendation_{index}_missing:{','.join(missing)}")
        gap = recommendation.get("identified_gap") or {}
        if gap.get("support_status") not in {"explicit_in_paper", "inferred_from_paper", "not_found"}:
            schema_errors.append(f"recommendation_{index}_gap_support_boundary_missing")
        extension_text = str(recommendation.get("extension_summary") or "").casefold()
        if "suggest" not in extension_text or "not a verified claim" not in extension_text:
            schema_errors.append(f"recommendation_{index}_suggestion_boundary_missing")
        for researcher in recommendation.get("potential_researcher_fit") or []:
            if "not verified as a supervisor" not in str(researcher.get("reason") or "").casefold():
                schema_errors.append(f"recommendation_{index}_researcher_boundary_missing")
    verification = verify_recommendations(
        recommendations,
        chunks_by_id,
        available_time=record.available_time,
    )
    target = "needs_reprocess" if locator_errors or schema_errors else "ai_reviewed"
    corrections: list[dict[str, Any]] = []
    candidate_corrections: list[dict[str, Any] | None] = []
    if fresh_response is not None:
        candidate_corrections.extend(
            [
                corrected_field(record, "recommendations_json", recommendations),
                corrected_field(record, "provider", fresh_response["provider"]),
                corrected_field(record, "model", fresh_response["model"]),
                corrected_field(record, "retrieval_mode", fresh_response["retrieval_mode"]),
                corrected_field(record, "top_k", fresh_response["top_k"]),
            ]
        )
    candidate_corrections.extend((
        corrected_field(record, "grounding_status", verification["grounding_status"]),
        corrected_field(
            record,
            "warnings_json",
            dedupe(
                list((fresh_response or {}).get("warnings") or record.warnings_json or [])
                + locator_warnings
                + verification["warnings"]
            ),
        ),
    ))
    for correction in candidate_corrections:
        if correction:
            corrections.append(correction)
    rationale = (
        "AI source/structure review confirmed eligible-corpus locators and explicit separation of paper facts, inferred/not-found gaps, "
        "new suggestions, feasibility heuristics, and unverified researcher references. This is not student or supervisor validation."
        if target == "ai_reviewed"
        else "AI review requires reprocessing: " + "; ".join(dedupe(locator_errors + schema_errors)) + "."
    )
    return ReviewDecision(
        item_type="thesis_recommendation",
        item_id=record.recommendation_id,
        target_status=target,
        rationale=rationale,
        content_sha256=sha256_value({"request": record.request_json, "recommendations": recommendations}),
        checks={
            "regenerated_with_current_deterministic_pipeline": fresh_response is not None,
            "regeneration_error": regeneration_error,
            "citation_locator_errors": locator_errors,
            "citation_locator_warnings": locator_warnings,
            "schema_errors": schema_errors,
            "verifier_status": verification["grounding_status"],
            "recommendation_count": len(recommendations),
            "citation_count": len(citations),
        },
        evidence=evidence,
        corrections=corrections,
    )


def review_artifact(session: Session, artifact: PaperArtifact) -> ReviewDecision:
    paper = session.get(Paper, artifact.paper_id)
    regeneration_error: str | None = None
    fresh_payload = artifact.generated_json
    fresh_generated_text = artifact.generated_text
    fresh_citations = list(artifact.citations_json or collect_nested_citations(artifact.generated_json))
    if paper is not None:
        try:
            chunks = list(
                session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id).order_by(Chunk.chunk_index)).all()
            )
            selected_chunks = select_source_chunks(chunks, max_chunks=12)
            source_pack = [source_entry(paper, chunk) for chunk in selected_chunks]
            bundle = build_intelligence_bundle(paper, source_pack)
            podcast = generate_podcast_script(bundle, source_pack)
            payloads = build_artifact_payloads(bundle, podcast)
            fresh_payload = payloads[artifact.artifact_type]
            fresh_citations = collect_artifact_citations(fresh_payload)
            fresh_generated_text = extract_generated_text(fresh_payload)
        except Exception as exc:  # fail closed; keep the original for audit
            regeneration_error = f"{type(exc).__name__}: {exc}"
    citations = fresh_citations
    evidence, locator_errors, locator_warnings = audit_citations(
        session,
        citations,
        expected_paper_id=artifact.paper_id,
    )
    schema_errors: list[str] = []
    if regeneration_error:
        schema_errors.append("deterministic_regeneration_failed")
    if paper is None:
        schema_errors.append("missing_parent_paper")
    elif paper.corpus_eligibility_status != "eligible":
        schema_errors.append("parent_paper_not_eligible")
    if artifact.generation_status != "generated":
        schema_errors.append(f"generation_status:{artifact.generation_status}")
    if not fresh_payload:
        schema_errors.append("empty_generated_payload")
    if artifact.artifact_type == "paper_intelligence_bundle":
        missing = sorted(ARTIFACT_REQUIRED_BUNDLE_FIELDS - set(fresh_payload))
        if missing:
            schema_errors.append("bundle_missing:" + ",".join(missing))
        for index, extension in enumerate(fresh_payload.get("possible_extensions") or [], start=1):
            if extension.get("support_status") != "suggested_by_system":
                schema_errors.append(f"extension_{index}_suggestion_boundary_missing")
    elif artifact.artifact_type == "podcast_script":
        if len(fresh_payload.get("script") or []) < 4:
            schema_errors.append("podcast_script_too_short")
        if not fresh_payload.get("cited_source_papers"):
            schema_errors.append("podcast_source_papers_missing")
    elif not fresh_generated_text and fresh_payload.get("support_status") != "not_found":
        schema_errors.append("generated_text_missing")
    valid_chunk_ids = {
        chunk.chunk_id
        for chunk in session.exec(select(Chunk).where(Chunk.paper_id == artifact.paper_id)).all()
    }
    verification = (
        verify_artifact_payload(
            artifact.artifact_type,
            fresh_payload,
            valid_chunk_ids,
            paper,
            source_chunk_count=len(valid_chunk_ids),
        )
        if paper
        else {"grounding_status": "unsupported", "warnings": ["Parent paper missing."]}
    )
    payload_chunk_ids = collect_cited_chunk_ids(fresh_payload)
    if payload_chunk_ids != {str(citation.get("chunk_id") or "") for citation in citations}:
        schema_errors.append("source_chunk_summary_mismatch")
    target = "needs_reprocess" if locator_errors or schema_errors else "ai_reviewed"
    corrections: list[dict[str, Any]] = []
    candidate_corrections = [
        corrected_field(artifact, "generated_json", fresh_payload),
        corrected_field(artifact, "generated_text", fresh_generated_text),
        corrected_field(artifact, "source_chunk_ids_json", sorted(payload_chunk_ids)),
        corrected_field(artifact, "citations_json", citations),
        corrected_field(artifact, "grounding_status", verification["grounding_status"]),
        corrected_field(artifact, "warnings_json", dedupe(list(artifact.warnings_json or []) + locator_warnings + verification["warnings"])),
    ]
    for correction in candidate_corrections:
        if correction:
            corrections.append(correction)
    rationale = (
        "AI source/structure review confirmed eligible-paper locators and required generated-output boundaries. "
        "Inferred plans/extensions and podcast wording remain AI drafts requiring human review before public reliance."
        if target == "ai_reviewed"
        else "AI review requires reprocessing: " + "; ".join(dedupe(locator_errors + schema_errors)) + "."
    )
    return ReviewDecision(
        item_type="paper_artifact",
        item_id=artifact.artifact_id,
        target_status=target,
        rationale=rationale,
        content_sha256=sha256_value(
            {"paper_id": artifact.paper_id, "artifact_type": artifact.artifact_type, "generated_json": fresh_payload}
        ),
        checks={
            "artifact_type": artifact.artifact_type,
            "regenerated_with_current_deterministic_pipeline": regeneration_error is None,
            "regeneration_max_chunks": 12,
            "regeneration_error": regeneration_error,
            "citation_locator_errors": locator_errors,
            "citation_locator_warnings": locator_warnings,
            "schema_errors": schema_errors,
            "verifier_status": verification["grounding_status"],
            "citation_count": len(citations),
        },
        evidence=evidence,
        corrections=corrections,
    )


def plan_reviews(session: Session) -> list[ReviewDecision]:
    decisions: list[ReviewDecision] = []
    decisions.extend(review_answer(session, item) for item in session.exec(select(RAGAnswer).order_by(RAGAnswer.answer_id)).all())
    decisions.extend(
        review_recommendation(session, item)
        for item in session.exec(select(ThesisRecommendation).order_by(ThesisRecommendation.recommendation_id)).all()
    )
    decisions.extend(
        review_artifact(session, item)
        for item in session.exec(select(PaperArtifact).order_by(PaperArtifact.artifact_id)).all()
    )
    return decisions


def record_for_decision(session: Session, decision: ReviewDecision) -> Any:
    model = {
        "rag_answer": RAGAnswer,
        "thesis_recommendation": ThesisRecommendation,
        "paper_artifact": PaperArtifact,
    }[decision.item_type]
    return session.get(model, decision.item_id)


def existing_version_event(session: Session, decision: ReviewDecision) -> ReviewEvent | None:
    events = session.exec(
        select(ReviewEvent)
        .where(ReviewEvent.item_type == decision.item_type)
        .where(ReviewEvent.item_id == decision.item_id)
        .where(ReviewEvent.reviewer_id == REVIEWER_ID)
        .where(ReviewEvent.request_id == REVIEW_REQUEST_ID)
        .order_by(desc(ReviewEvent.created_at), desc(ReviewEvent.review_event_id))
    ).all()
    # A review-version identifier describes the protocol, not the immutable
    # generated payload.  Reusing an event after that payload (or the resulting
    # decision) changed would suppress a necessary append-only review event and
    # can falsely report status drift.  Idempotence therefore requires an exact
    # match on protocol, payload hash, and decision.
    for event in events:
        diff = event.diff_json if isinstance(event.diff_json, dict) else {}
        if (
            diff.get("content_sha256") == decision.content_sha256
            and event.new_status == decision.target_status
        ):
            return event
    return None


def make_review_event(
    session: Session,
    decision: ReviewDecision,
    *,
    previous_status: str,
    field_changes: dict[str, Any],
) -> ReviewEvent:
    latest = session.exec(
        select(ReviewEvent).order_by(desc(ReviewEvent.created_at), desc(ReviewEvent.review_event_id)).limit(1)
    ).first()
    created_at = utc_now()
    event_id = str(uuid.uuid4())
    previous_hash = latest.event_hash if latest else None
    diff = json_safe({
        "review_version": REVIEW_VERSION,
        "content_sha256": decision.content_sha256,
        "field_changes": field_changes,
        "review": {
            "decision": decision.target_status,
            "rationale": decision.rationale,
            "checks": decision.checks,
            "evidence": decision.evidence,
            "corrections": [sanitized_correction(correction) for correction in decision.corrections],
            "review_notice": AI_REVIEW_NOTICE,
            "human_validation": False,
        },
    })
    event_hash = ReviewEvent.calculate_hash(
        review_event_id=event_id,
        previous_event_hash=previous_hash,
        item_type=decision.item_type,
        item_id=decision.item_id,
        action="ai_reviewed" if decision.target_status == "ai_reviewed" else "marked_needs_reprocess",
        previous_status=previous_status,
        new_status=decision.target_status,
        reviewer_id=REVIEWER_ID,
        reviewer_name=REVIEWER_NAME,
        reviewer_type=REVIEWER_TYPE,
        reviewer_role=REVIEWER_ROLE,
        request_id=REVIEW_REQUEST_ID,
        reviewer_notes=decision.rationale,
        diff_json=diff,
        created_at=created_at,
    )
    return ReviewEvent(
        review_event_id=event_id,
        item_type=decision.item_type,
        item_id=decision.item_id,
        action="ai_reviewed" if decision.target_status == "ai_reviewed" else "marked_needs_reprocess",
        previous_status=previous_status,
        new_status=decision.target_status,
        reviewer_name=REVIEWER_NAME,
        reviewer_id=REVIEWER_ID,
        reviewer_type=REVIEWER_TYPE,
        reviewer_role=REVIEWER_ROLE,
        request_id=REVIEW_REQUEST_ID,
        reviewer_notes=decision.rationale,
        diff_json=diff,
        previous_event_hash=previous_hash,
        event_hash=event_hash,
        created_at=created_at,
    )


def apply_reviews(session: Session, decisions: list[ReviewDecision]) -> dict[str, Any]:
    created_events = 0
    changed_records = 0
    skipped_existing = 0
    event_rows: list[dict[str, Any]] = []
    for decision in decisions:
        record = record_for_decision(session, decision)
        if record is None:
            raise RuntimeError(f"Review target disappeared: {decision.item_type}/{decision.item_id}")
        prior_event = existing_version_event(session, decision)
        if prior_event is not None:
            if record.review_status != prior_event.new_status:
                raise RuntimeError(f"Review status drift after recorded event: {decision.item_type}/{decision.item_id}")
            skipped_existing += 1
            event_rows.append({"item_type": decision.item_type, "item_id": decision.item_id, "event_id": prior_event.review_event_id, "event_hash": prior_event.event_hash, "result": "existing"})
            continue
        previous_status = record.review_status
        field_changes: dict[str, Any] = {}
        for correction in decision.corrections:
            field_name = correction["field"]
            before = getattr(record, field_name)
            after = correction["after"]
            if before != after:
                field_changes[field_name] = {
                    "before_sha256": sha256_value(before),
                    "after_sha256": sha256_value(after),
                    "reason": correction.get("reason"),
                }
                setattr(record, field_name, after)
        for field_name, after in (
            ("review_status", decision.target_status),
            ("reviewer_notes", decision.rationale),
            ("reviewed_by", REVIEWER_ID),
        ):
            before = getattr(record, field_name)
            if before != after:
                field_changes[field_name] = {"before": before, "after": after}
                setattr(record, field_name, after)
        before_reviewed_at = record.reviewed_at
        record.reviewed_at = utc_now()
        field_changes["reviewed_at"] = {"before": before_reviewed_at, "after": record.reviewed_at}
        if isinstance(record, PaperArtifact):
            record.updated_at = utc_now()
        event = make_review_event(session, decision, previous_status=previous_status, field_changes=field_changes)
        session.add(record)
        session.add(event)
        session.commit()
        created_events += 1
        changed_records += 1
        event_rows.append({"item_type": decision.item_type, "item_id": decision.item_id, "event_id": event.review_event_id, "event_hash": event.event_hash, "result": "created"})
    events = list(session.exec(select(ReviewEvent).order_by(ReviewEvent.created_at, ReviewEvent.review_event_id)).all())
    integrity = verify_review_event_chain(events)
    if integrity["status"] != "verified":
        raise RuntimeError(f"Review-event chain failed after apply: {integrity}")
    return {
        "created_events": created_events,
        "changed_records": changed_records,
        "skipped_existing": skipped_existing,
        "review_event_integrity": integrity,
        "events": event_rows,
    }


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as destination_db:
        source_db.backup(destination_db)


def database_engine(path: Path) -> Any:
    return create_engine(f"sqlite:///{path.resolve()}", connect_args={"check_same_thread": False})


def status_counts(decisions: list[ReviewDecision]) -> dict[str, Any]:
    return {
        "total": len(decisions),
        "by_item_type": dict(Counter(item.item_type for item in decisions)),
        "by_target_status": dict(Counter(item.target_status for item in decisions)),
        "by_item_type_and_status": {
            f"{item_type}:{status}": count
            for (item_type, status), count in sorted(Counter((item.item_type, item.target_status) for item in decisions).items())
        },
        "items_with_corrections": sum(bool(item.corrections) for item in decisions),
        "citation_evidence_locator_count": sum(len(item.evidence) for item in decisions),
    }


def disposable_idempotence(database: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ttlab-generated-review-") as directory:
        copy_path = Path(directory) / "review-copy.db"
        sqlite_backup(database, copy_path)
        engine = database_engine(copy_path)
        compatibility = compatibility_report(engine)
        with Session(engine) as session:
            decisions = plan_reviews(session)
            preexisting_version_events = sum(
                existing_version_event(session, decision) is not None
                for decision in decisions
            )
            first = apply_reviews(session, decisions)
            # Reapply the exact reviewed plan to prove write/event idempotence;
            # the live planning pass independently regenerates the outputs.
            second = apply_reviews(session, decisions)
            final_counts = {
                "rag_answer": len(session.exec(select(RAGAnswer)).all()),
                "thesis_recommendation": len(session.exec(select(ThesisRecommendation)).all()),
                "paper_artifact": len(session.exec(select(PaperArtifact)).all()),
                "review_event": len(session.exec(select(ReviewEvent)).all()),
            }
        expected_new_events = len(decisions) - preexisting_version_events
        if (
            first["created_events"] != expected_new_events
            or first["changed_records"] != expected_new_events
            or first["skipped_existing"] != preexisting_version_events
        ):
            raise RuntimeError("Disposable first pass did not create or reuse exactly one review per generated output")
        if (
            second["created_events"]
            or second["changed_records"]
            or second["skipped_existing"] != len(decisions)
        ):
            raise RuntimeError("Disposable second pass was not idempotent")
        return {
            "status": "PASS",
            "database_input_sha256": sha256_file(database),
            "compatibility": compatibility,
            "planned": status_counts(decisions),
            "preexisting_version_events": preexisting_version_events,
            "first_pass": {key: first[key] for key in ("created_events", "changed_records", "skipped_existing", "review_event_integrity")},
            "second_pass": {key: second[key] for key in ("created_events", "changed_records", "skipped_existing", "review_event_integrity")},
            "final_counts": final_counts,
            "live_database_mutated": False,
        }


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def write_outputs(
    output_dir: Path,
    decisions: list[ReviewDecision],
    apply_result: dict[str, Any] | None,
    idempotence: dict[str, Any],
    compatibility: dict[str, Any],
    database_hash_before: str,
    database_hash_after: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [decision.sanitized() for decision in decisions]
    review_path = output_dir / "generated_output_reviews.jsonl"
    review_path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
    summary = {
        "schema_version": 1,
        "generated_at": utc_now().isoformat(),
        "review_version": REVIEW_VERSION,
        "reviewer_id": REVIEWER_ID,
        "reviewer_type": REVIEWER_TYPE,
        "human_validation": False,
        "review_notice": AI_REVIEW_NOTICE,
        "counts": status_counts(decisions),
        "compatibility": compatibility,
        "apply_result": apply_result,
        "residual_limitations": [
            "AI review is not human approval, author validation, supervisor endorsement, or a user study.",
            "Citation-locator and lexical checks do not prove complete semantic entailment.",
            "Outputs marked needs_reprocess remain stored for audit history and must not be presented as reviewed guidance.",
            "Recommendations and possible extensions remain heuristic suggestions whose novelty, feasibility, data access, and supervisor fit require external confirmation.",
        ],
    }
    summary_path = output_dir / "generated_output_review_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    idempotence_path = output_dir / "idempotence_evidence.json"
    idempotence_path.write_text(json.dumps(idempotence, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "generated_at": utc_now().isoformat(),
        "review_version": REVIEW_VERSION,
        "code_commit": git_commit(),
        "review_code_sha256": sha256_file(Path(__file__)),
        "database_sha256_before": database_hash_before,
        "database_sha256_after": database_hash_after,
        "database_bytes_redistributed": False,
        "reviewer_type": REVIEWER_TYPE,
        "human_validation": False,
        "outputs": {
            review_path.name: sha256_file(review_path),
            summary_path.name: sha256_file(summary_path),
            idempotence_path.name: sha256_file(idempotence_path),
        },
    }
    manifest_path = output_dir / "generated_output_review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def run(database: Path, *, apply_live: bool, output_dir: Path) -> dict[str, Any]:
    database = database.resolve()
    idempotence = disposable_idempotence(database)
    before_hash = sha256_file(database)
    engine = database_engine(database)
    compatibility = compatibility_report(engine)
    with Session(engine) as session:
        decisions = plan_reviews(session)
        result = apply_reviews(session, decisions) if apply_live else None
        if apply_live:
            second = apply_reviews(session, plan_reviews(session))
            if second["created_events"] or second["changed_records"]:
                raise RuntimeError("Live second pass was not idempotent")
            result["live_second_pass"] = {
                key: second[key]
                for key in ("created_events", "changed_records", "skipped_existing", "review_event_integrity")
            }
    after_hash = sha256_file(database)
    manifest = write_outputs(
        output_dir,
        decisions,
        result,
        idempotence,
        compatibility,
        before_hash,
        after_hash,
    )
    return {
        "status": "PASS",
        "mode": "apply_live" if apply_live else "audit_only",
        "counts": status_counts(decisions),
        "apply_result": result,
        "idempotence": idempotence,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--apply-live", action="store_true", help="Apply only after the built-in disposable two-pass proof succeeds.")
    args = parser.parse_args()
    print(json.dumps(run(args.database, apply_live=args.apply_live, output_dir=args.output_dir), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
