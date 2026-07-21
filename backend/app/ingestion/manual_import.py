from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import (
    Author,
    AuthorTopic,
    Chunk,
    Paper,
    PaperArtifact,
    PaperTopic,
    RAGAnswer,
    ThesisRecommendation,
)
from app.ingestion.metadata_cleaner import (
    build_metadata_provenance,
    clean_author_name,
    ensure_author_identity,
    is_malformed_author_name,
    repair_author_identities,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def load_seed(seed_path: Path) -> list[dict[str, Any]]:
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Seed file must contain a JSON array.")
    return [record for record in data if isinstance(record, dict)]


def upsert_papers(session: Session, records: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "missing_pdf": 0,
        "authors": 0,
        "reviewed_field_conflicts": 0,
        "descendants_invalidated": 0,
    }
    for record in records:
        paper_id = record.get("paper_id")
        title = record.get("title")
        if not paper_id or not title:
            summary["skipped"] += 1
            continue

        existing = session.get(Paper, str(paper_id))
        authors = [
            clean_author_name(name)
            for name in normalize_list(record.get("authors"))
            if not is_malformed_author_name(name)
        ]
        pdf_url = validated_web_url(record.get("pdf_url"), field_name="pdf_url")
        local_pdf_path = record.get("local_pdf_path") or record.get("pdf_path") or (existing.local_pdf_path if existing else None)
        pdf_text_status = record.get("pdf_text_status") or ("not_extracted" if pdf_url or local_pdf_path else "missing_pdf")
        if (
            existing is not None
            and existing.pdf_text_status in {"downloaded", "extracted", "no_text", "blank_pdf", "scanned_pdf", "extraction_failed"}
            and pdf_text_status in {"missing_pdf", "not_extracted"}
        ):
            pdf_text_status = existing.pdf_text_status
        if pdf_text_status == "missing_pdf":
            summary["missing_pdf"] += 1
        pdf_unavailability_reason = existing.pdf_unavailability_reason if existing else None
        pdf_unavailability_detail = existing.pdf_unavailability_detail if existing else None
        if not pdf_url and not local_pdf_path:
            pdf_unavailability_reason = "no_pdf_url"
            pdf_unavailability_detail = "No permitted direct PDF URL or local PDF path was supplied."

        provenance, field_reviews = build_metadata_provenance(
            record,
            source="ttlab_archive_seed" if record.get("raw_scraped") else "manual_seed",
        )
        if existing is not None:
            provenance = {**provenance, **dict(existing.metadata_provenance or {})}
            field_reviews = {**field_reviews, **dict(existing.metadata_field_reviews or {})}
        values = {
            "title": str(title),
            "authors": authors,
            "year": safe_int(record.get("year")),
            "publication_date_raw": optional_str(record.get("publication_date_raw") or record.get("publication_date")),
            "venue": optional_str(record.get("venue")),
            "abstract": optional_str(record.get("abstract")),
            "source_url": validated_web_url(record.get("source_url"), field_name="source_url"),
            "post_url": validated_web_url(record.get("post_url"), field_name="post_url"),
            "pdf_url": pdf_url,
            "local_pdf_path": optional_str(local_pdf_path),
            "pdf_unavailability_reason": pdf_unavailability_reason,
            "pdf_unavailability_detail": pdf_unavailability_detail,
            "doi": optional_str(record.get("doi")),
            "keywords": normalize_list(record.get("keywords")),
            "topics": normalize_list(record.get("topics")),
            "all_urls": [
                url
                for index, value in enumerate(normalize_list(record.get("all_urls")))
                if (url := validated_web_url(value, field_name=f"all_urls[{index}]")) is not None
            ],
            "raw_record": record,
            "metadata_provenance": provenance,
            "metadata_field_reviews": field_reviews,
            "ingestion_status": str(record.get("ingestion_status") or "discovered"),
            "pdf_text_status": str(pdf_text_status),
            "updated_at": utc_now(),
        }

        if existing is None:
            session.add(Paper(paper_id=str(paper_id), review_status="needs_review", **values))
            summary["created"] += 1
        else:
            accepted_changes: set[str] = set()
            existing_provenance = dict(existing.metadata_provenance or {})
            existing_reviews = dict(existing.metadata_field_reviews or {})
            for key, value in values.items():
                if key in {"metadata_provenance", "metadata_field_reviews", "raw_record", "updated_at"}:
                    continue
                if getattr(existing, key) == value:
                    continue
                if key in REVIEWABLE_METADATA_FIELDS and field_is_reviewed(existing, key):
                    conflict = {
                        "incoming_value": value,
                        "preserved_value": getattr(existing, key),
                        "source": "automated_import",
                        "recorded_at": utc_now().isoformat(),
                        "status": "conflict_needs_human_review",
                    }
                    prior = dict(existing_provenance.get(key) or {})
                    prior["incoming_conflict"] = conflict
                    existing_provenance[key] = prior
                    summary["reviewed_field_conflicts"] += 1
                    continue
                setattr(existing, key, value)
                accepted_changes.add(key)
            existing.raw_record = record
            existing.metadata_provenance = {**provenance, **existing_provenance}
            existing.metadata_field_reviews = {**field_reviews, **existing_reviews}
            existing.updated_at = utc_now()
            if accepted_changes.intersection(MATERIAL_SOURCE_FIELDS):
                retained_local_path = (
                    existing.local_pdf_path if "local_pdf_path" in accepted_changes else None
                )
                invalidate_paper_descendants(
                    session,
                    existing,
                    retained_local_pdf_path=retained_local_path,
                    reason="material_source_change_requires_reprocessing",
                )
                summary["descendants_invalidated"] += 1
            if accepted_changes.intersection(REVIEWABLE_METADATA_FIELDS):
                existing.review_status = "needs_review"
                reset_dependent_graph_reviews_for_paper(
                    session,
                    existing.paper_id,
                    reason="Paper metadata changed; topic relationships require re-review.",
                )
                invalidate_generated_outputs_for_paper(
                    session,
                    existing.paper_id,
                    reason="Paper metadata changed; generated outputs require regeneration and re-review.",
                )
            session.add(existing)
            summary["updated"] += 1

        for author_name in authors:
            if upsert_author(session, author_name):
                summary["authors"] += 1

    session.commit()
    repair_summary = repair_author_identities(session)
    summary["authors_recovered"] = repair_summary["source_backed_authors_recovered"]
    update_author_counts(session)
    return summary


REVIEWED_STATES = {"reviewed", "approved"}
REVIEWABLE_METADATA_FIELDS = {
    "title",
    "authors",
    "year",
    "publication_date_raw",
    "venue",
    "abstract",
    "source_url",
    "post_url",
    "pdf_url",
    "doi",
    "keywords",
    "topics",
}
MATERIAL_SOURCE_FIELDS = {"source_url", "post_url", "pdf_url", "local_pdf_path"}


def field_is_reviewed(paper: Paper, field_name: str) -> bool:
    field_reviews = paper.metadata_field_reviews if isinstance(paper.metadata_field_reviews, dict) else {}
    return paper.review_status in REVIEWED_STATES or str(field_reviews.get(field_name) or "") in REVIEWED_STATES


def invalidate_paper_descendants(
    session: Session,
    paper: Paper,
    *,
    retained_local_pdf_path: str | None = None,
    reason: str = "material_source_change_requires_reprocessing",
) -> None:
    """Invalidate derived text/chunks when the accepted source identity changes."""

    session.exec(delete(Chunk).where(Chunk.paper_id == paper.paper_id))
    reset_dependent_graph_reviews_for_paper(
        session,
        paper.paper_id,
        reason="Paper source identity changed; topic relationships require re-review.",
    )
    paper.local_pdf_path = retained_local_pdf_path
    paper.pdf_text_status = "not_extracted" if paper.pdf_url or retained_local_pdf_path else "missing_pdf"
    paper.extracted_json_path = None
    paper.extracted_text_path = None
    paper.extraction_generation_id = None
    paper.extraction_input_pdf_sha256 = None
    paper.extraction_config_sha256 = None
    paper.chunk_extraction_generation_id = None
    paper.chunk_generation_id = None
    paper.public_index_generation_id = None
    paper.extraction_diagnostics = {
        "status": "invalidated_source_change",
        "warnings": ["Derived extraction and chunks were invalidated after a material source change."],
    }
    paper.extraction_content_type = "unknown"
    paper.page_count = None
    paper.total_char_count = 0
    paper.total_word_count = 0
    paper.pages_with_text = 0
    paper.pages_without_text = 0
    paper.possible_scanned_pdf = False
    paper.chunk_count = 0
    paper.corpus_eligibility_status = "needs_review"
    paper.corpus_exclusion_reason = reason
    paper.pdf_title_match_status = "not_assessed"
    paper.pdf_title_match_score = None
    paper.extraction_review_status = "needs_review"
    paper.extraction_reviewer_notes = None
    paper.extraction_reviewed_at = None
    paper.extraction_reviewed_by = None
    paper.publication_status = "pending_review"
    paper.public_access_level = "hidden"
    paper.rights_status = "unknown"
    invalidate_generated_outputs_for_paper(
        session,
        paper.paper_id,
        reason="Source or metadata identity changed; regenerate and reapprove this output.",
    )


def invalidate_generated_outputs_for_paper(
    session: Session,
    paper_id: str,
    *,
    reason: str,
) -> dict[str, list[str]]:
    """Reset approvals on generated records whose evidence cites a changed paper."""

    invalidated: dict[str, list[str]] = {
        "artifact_ids": [],
        "answer_ids": [],
        "recommendation_ids": [],
    }
    for artifact in session.exec(select(PaperArtifact).where(PaperArtifact.paper_id == paper_id)).all():
        if artifact.review_status != "needs_reprocess":
            invalidated["artifact_ids"].append(artifact.artifact_id)
        artifact.review_status = "needs_reprocess"
        artifact.reviewer_notes = None
        artifact.reviewed_at = None
        artifact.reviewed_by = None
        artifact.warnings_json = append_warning(artifact.warnings_json, reason)
        artifact.updated_at = utc_now()
        session.add(artifact)

    for answer in session.exec(select(RAGAnswer)).all():
        cites_paper = paper_id in list(answer.cited_paper_ids or []) or any(
            isinstance(item, dict) and item.get("paper_id") == paper_id
            for item in [*list(answer.citations_json or []), *list(answer.retrieved_chunks_json or [])]
        )
        if not cites_paper:
            continue
        if answer.review_status != "needs_reprocess":
            invalidated["answer_ids"].append(answer.answer_id)
        answer.review_status = "needs_reprocess"
        answer.reviewer_notes = None
        answer.reviewed_at = None
        answer.reviewed_by = None
        answer.citation_correct = None
        answer.answer_faithfulness_score = None
        answer.usefulness_score = None
        answer.warnings_json = append_warning(answer.warnings_json, reason)
        session.add(answer)

    for recommendation in session.exec(select(ThesisRecommendation)).all():
        payloads = list(recommendation.recommendations_json or [])
        corrected = recommendation.corrected_recommendations_json
        if isinstance(corrected, dict):
            corrected_items = corrected.get("items")
            if isinstance(corrected_items, list):
                payloads.extend(item for item in corrected_items if isinstance(item, dict))
        cites_paper = any(
            isinstance(item, dict)
            and (
                item.get("paper_id") == paper_id
                or any(
                    isinstance(citation, dict) and citation.get("paper_id") == paper_id
                    for citation in list(item.get("citations") or [])
                )
            )
            for item in payloads
        )
        if not cites_paper:
            continue
        if recommendation.review_status != "needs_reprocess":
            invalidated["recommendation_ids"].append(recommendation.recommendation_id)
        recommendation.review_status = "needs_reprocess"
        recommendation.reviewer_notes = None
        recommendation.reviewed_at = None
        recommendation.reviewed_by = None
        recommendation.warnings_json = append_warning(recommendation.warnings_json, reason)
        session.add(recommendation)
    return invalidated


def append_warning(existing: list[str] | None, warning: str) -> list[str]:
    return list(dict.fromkeys([*list(existing or []), warning]))


def reset_dependent_graph_reviews_for_paper(
    session: Session,
    paper_id: str,
    *,
    reason: str,
) -> dict[str, list[str]]:
    """Fail closed on graph approvals derived from changed paper facts."""

    reset: dict[str, list[str]] = {"paper_topic_ids": [], "author_topic_ids": []}
    now = utc_now()
    for link in session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper_id)).all():
        if link.review_status != "needs_review":
            reset["paper_topic_ids"].append(link.link_id)
        link.review_status = "needs_review"
        link.reviewer_notes = reason
        link.reviewed_at = None
        link.reviewed_by = None
        link.updated_at = now
        session.add(link)
    for link in session.exec(select(AuthorTopic)).all():
        evidence = link.evidence_json if isinstance(link.evidence_json, list) else []
        if not any(isinstance(item, dict) and item.get("paper_id") == paper_id for item in evidence):
            continue
        if link.review_status != "needs_review":
            reset["author_topic_ids"].append(link.link_id)
        link.review_status = "needs_review"
        link.reviewer_notes = reason
        link.reviewed_at = None
        link.reviewed_by = None
        link.updated_at = now
        session.add(link)
    return reset


def upsert_author(session: Session, author_name: str) -> bool:
    _author, created = ensure_author_identity(session, author_name, source="seed_import")
    return created


def update_author_counts(session: Session) -> None:
    papers = list(session.exec(select(Paper)).all())
    counts: dict[str, int] = {}
    for paper in papers:
        for author_name in paper.authors:
            counts[clean_author_name(author_name)] = counts.get(clean_author_name(author_name), 0) + 1
    for author in session.exec(select(Author)).all():
        author.paper_count = 0 if author.identity_status in {"merged", "invalid"} else counts.get(author.canonical_name or author.name, 0)
        author.updated_at = utc_now()
        session.add(author)
    session.commit()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def validated_web_url(value: Any, *, field_name: str) -> str | None:
    normalized = optional_str(value)
    if normalized is None:
        return None
    if len(normalized) > 2_048:
        raise ValueError(f"{field_name} exceeds 2048 characters")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field_name} must be an http(s) URL without embedded credentials")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import seed paper records into SQLite.")
    parser.add_argument("--seed", default="data/seed/papers.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    seed_path = Path(args.seed)
    create_db_and_tables()
    records = load_seed(seed_path)
    with Session(engine) as session:
        summary = upsert_papers(session, records)
    print(
        "created={created} updated={updated} skipped={skipped} "
        "authors={authors} missing_pdf={missing_pdf}".format(**summary)
    )


if __name__ == "__main__":
    main()
