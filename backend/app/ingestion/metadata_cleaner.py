from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from pathlib import Path

from sqlmodel import Session, delete, select

from app.db import create_db_and_tables, engine
from app.models import Author, AuthorAlias, AuthorTopic, Paper
from app.ingestion.ttlab_page import parse_year, split_authors
from app.ingestion.pdf_parser import title_match_diagnostic_pages


MALFORMED_AUTHOR_LABELS = {
    "click to view",
    "click here",
    "download",
    "download pdf",
    "read more",
    "view article",
    "view paper",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def clean_author_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" \t\r\n,;|")


def normalize_author_key(value: str) -> str:
    cleaned = clean_author_name(value)
    decomposed = unicodedata.normalize("NFKD", cleaned)
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_like.casefold()).strip()


def is_malformed_author_name(value: str | None) -> bool:
    if not value:
        return True
    normalized = normalize_author_key(value)
    if normalized in MALFORMED_AUTHOR_LABELS:
        return True
    return normalized.startswith("click to ") or normalized.startswith("download ")


def alias_id_for(author_id: int, normalized_alias: str) -> str:
    digest = hashlib.sha1(f"{author_id}|{normalized_alias}".encode("utf-8")).hexdigest()[:16]
    return f"author-alias-{digest}"


def ensure_alias(
    session: Session,
    author: Author,
    alias: str,
    *,
    source: str,
    review_status: str = "needs_review",
) -> AuthorAlias | None:
    if author.id is None or is_malformed_author_name(alias):
        return None
    cleaned = clean_author_name(alias)
    normalized = normalize_author_key(cleaned)
    alias_id = alias_id_for(author.id, normalized)
    record = session.get(AuthorAlias, alias_id)
    if record is None:
        record = AuthorAlias(
            alias_id=alias_id,
            canonical_author_id=author.id,
            alias=cleaned,
            normalized_alias=normalized,
            source=source,
            review_status=review_status,
        )
    else:
        record.alias = cleaned
        record.normalized_alias = normalized
        record.source = source or record.source
        record.updated_at = utc_now()
    session.add(record)
    return record


def active_author_for_name(session: Session, author_name: str) -> Author | None:
    normalized = normalize_author_key(author_name)
    candidates = list(
        session.exec(
            select(Author)
            .where(Author.normalized_name == normalized)
            .where(Author.identity_status.notin_(["merged", "invalid"]))
            .order_by(Author.id)
        ).all()
    )
    if candidates:
        return candidates[0]
    alias = session.exec(
        select(AuthorAlias).where(AuthorAlias.normalized_alias == normalized).order_by(AuthorAlias.created_at)
    ).first()
    if alias is None:
        return None
    author = session.get(Author, alias.canonical_author_id)
    return author if author and author.identity_status not in {"merged", "invalid"} else None


def ensure_author_identity(session: Session, author_name: str, *, source: str = "seed_import") -> tuple[Author, bool]:
    cleaned = clean_author_name(author_name)
    if is_malformed_author_name(cleaned):
        raise ValueError(f"Malformed author label is not an identity: {author_name!r}")
    normalized = normalize_author_key(cleaned)
    author = active_author_for_name(session, cleaned)
    if author is None:
        # Backward-compatible path for rows created before canonical columns
        # existed. Exact names are safe to initialize without identity guessing.
        author = session.exec(select(Author).where(Author.name == cleaned)).first()
    created = author is None
    if author is None:
        author = Author(
            name=cleaned,
            canonical_name=cleaned,
            normalized_name=normalized,
            review_status="needs_review",
            identity_status="unresolved",
            identity_review_status="needs_review",
        )
        session.add(author)
        session.flush()
    else:
        author.canonical_name = author.canonical_name or author.name
        author.normalized_name = normalized if not author.normalized_name else author.normalized_name
        author.updated_at = utc_now()
        session.add(author)
    ensure_alias(session, author, cleaned, source=source)
    ensure_alias(session, author, author.canonical_name or author.name, source="canonical_name")
    return author, created


def build_metadata_provenance(record: dict[str, Any], *, source: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Describe where populated metadata came from without asserting correctness."""

    provenance: dict[str, Any] = {}
    reviews: dict[str, str] = {}
    for field_name in (
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
    ):
        value = record.get(field_name)
        if value in (None, "", []):
            continue
        provenance[field_name] = {
            "source": source,
            "source_url": record.get("post_url") or record.get("source_url"),
            "status": "observed_unverified",
        }
        reviews[field_name] = "needs_review"
    return provenance, reviews


def backfill_paper_data_quality(paper: Paper) -> int:
    """Add explicit provenance/review state to legacy values without verifying them."""

    changed = 0
    provenance = dict(paper.metadata_provenance or {})
    reviews = dict(paper.metadata_field_reviews or {})
    raw = paper.raw_record if isinstance(paper.raw_record, dict) else {}
    for field_name in (
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
    ):
        value = getattr(paper, field_name)
        if value in (None, "", []):
            continue
        if field_name not in provenance:
            provenance[field_name] = {
                "source": "retained_raw_record" if field_name in raw else "legacy_database",
                "source_url": paper.post_url or paper.source_url,
                "status": "observed_unverified",
            }
            changed += 1
        reviews.setdefault(field_name, "needs_review")
    paper.metadata_provenance = provenance
    paper.metadata_field_reviews = reviews

    if not paper.pdf_unavailability_reason:
        reason_map = {
            "invalid_pdf": "invalid_pdf",
            "scanned_pdf": "scanned_pdf",
            "extraction_failed": "extraction_failure",
            "no_text": "extraction_failure",
            "blank_pdf": "extraction_failure",
            "download_failed": "network_error",
        }
        reason = reason_map.get(paper.pdf_text_status)
        if paper.pdf_text_status == "missing_pdf" and not paper.local_pdf_path:
            reason = "no_pdf_url" if not paper.pdf_url else "not_found"
        if reason:
            paper.pdf_unavailability_reason = reason
            paper.pdf_unavailability_detail = (
                "Legacy status was deterministically mapped during migration; inspect source/download logs for detail."
            )
            changed += 1
    return changed


def recover_bibliographic_fields_from_raw(paper: Paper) -> dict[str, Any] | None:
    """Recover the known archive-parser failure from retained source paragraphs."""

    raw = paper.raw_record if isinstance(paper.raw_record, dict) else {}
    scraped = raw.get("raw_scraped") if isinstance(raw.get("raw_scraped"), dict) else raw.get("raw_record")
    if isinstance(scraped, dict) and isinstance(scraped.get("raw_scraped"), dict):
        scraped = scraped["raw_scraped"]
    if not isinstance(scraped, dict):
        return None
    paragraphs = scraped.get("paragraphs")
    if not isinstance(paragraphs, list):
        return None
    cleaned = [re.sub(r"\s+", " ", str(item)).strip() for item in paragraphs]
    for index, paragraph in enumerate(cleaned):
        if normalize_author_key(paragraph) != "click to view":
            continue
        if index + 1 >= len(cleaned):
            return None
        authors = [name for name in split_authors(cleaned[index + 1]) if not is_malformed_author_name(name)]
        if not authors:
            return None
        venue = None
        publication_date_raw = None
        remaining = cleaned[index + 2 :]
        if remaining:
            first = remaining[0]
            looks_like_date_only = bool(
                re.match(
                    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
                    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
                    r"\d{1,2}[\s,/-])",
                    first,
                    re.IGNORECASE,
                )
            )
            if parse_year(first) and looks_like_date_only:
                publication_date_raw = first
            else:
                venue = first or None
        if publication_date_raw is None:
            for candidate in remaining[1:] if venue else remaining:
                if parse_year(candidate):
                    publication_date_raw = candidate
                    break
        return {
            "authors": authors,
            "venue": venue,
            "publication_date_raw": publication_date_raw,
            "source": "raw_record.raw_scraped.paragraphs",
        }
    return None


def repair_author_identities(session: Session) -> dict[str, int]:
    """Idempotently remove UI labels and link safe formatting aliases.

    Only exact normalized-name variants are merged. Initial-to-full-name guesses such
    as ``P. Hosein`` to ``Patrick Hosein`` remain separate and require review.
    """

    summary = {
        "paper_author_labels_removed": 0,
        "paper_author_names_normalized": 0,
        "authors_initialized": 0,
        "authors_merged": 0,
        "authors_invalidated": 0,
        "aliases_created": 0,
        "source_backed_authors_recovered": 0,
        "source_backed_venues_recovered": 0,
        "paper_quality_fields_backfilled": 0,
    }
    authors = list(session.exec(select(Author).order_by(Author.id)).all())
    canonical_by_key: dict[str, Author] = {}
    for author in authors:
        cleaned = clean_author_name(author.name)
        if is_malformed_author_name(cleaned):
            if author.identity_status != "invalid":
                summary["authors_invalidated"] += 1
            author.identity_status = "invalid"
            author.identity_review_status = "rejected"
            author.identity_review_notes = "Removed deterministic interface-action label from publication authors."
            author.paper_count = 0
            if author.id is not None:
                session.exec(delete(AuthorTopic).where(AuthorTopic.author_id == author.id))
            session.add(author)
            continue
        normalized = normalize_author_key(cleaned)
        canonical = canonical_by_key.get(normalized)
        if canonical is None:
            canonical = author
            canonical_by_key[normalized] = canonical
            if not author.canonical_name or not author.normalized_name:
                summary["authors_initialized"] += 1
            author.canonical_name = author.canonical_name or cleaned
            author.normalized_name = normalized
            if author.identity_status in {"merged", "invalid"}:
                author.identity_status = "unresolved"
                author.merged_into_author_id = None
            session.add(author)
            before = session.get(AuthorAlias, alias_id_for(author.id, normalized)) if author.id is not None else None
            ensure_alias(session, author, cleaned, source="identity_repair")
            if before is None:
                summary["aliases_created"] += 1
            continue
        if author.id == canonical.id:
            continue
        if author.identity_status != "merged" or author.merged_into_author_id != canonical.id:
            summary["authors_merged"] += 1
        author.canonical_name = canonical.canonical_name or canonical.name
        author.normalized_name = normalized
        author.identity_status = "merged"
        author.identity_review_status = "needs_review"
        author.identity_review_notes = "Merged only as an exact normalized spelling/punctuation variant."
        author.merged_into_author_id = canonical.id
        author.paper_count = 0
        if author.id is not None:
            session.exec(delete(AuthorTopic).where(AuthorTopic.author_id == author.id))
        before = session.get(AuthorAlias, alias_id_for(canonical.id, normalized)) if canonical.id is not None else None
        ensure_alias(session, canonical, cleaned, source="identity_repair")
        if before is None:
            summary["aliases_created"] += 1
        session.add(author)

    session.flush()
    for paper in session.exec(select(Paper)).all():
        summary["paper_quality_fields_backfilled"] += backfill_paper_data_quality(paper)
        recovered = None
        if not paper.authors or all(is_malformed_author_name(name) for name in paper.authors):
            recovered = recover_bibliographic_fields_from_raw(paper)
        if recovered:
            paper.authors = list(recovered["authors"])
            summary["source_backed_authors_recovered"] += 1
            if recovered.get("venue"):
                paper.venue = str(recovered["venue"])
                summary["source_backed_venues_recovered"] += 1
            if recovered.get("publication_date_raw") and not paper.publication_date_raw:
                paper.publication_date_raw = str(recovered["publication_date_raw"])
            provenance = dict(paper.metadata_provenance or {})
            reviews = dict(paper.metadata_field_reviews or {})
            for field_name in ("authors", "venue", "publication_date_raw"):
                if recovered.get(field_name):
                    provenance[field_name] = {
                        "source": recovered["source"],
                        "source_url": paper.post_url or paper.source_url,
                        "status": "source_recovered_needs_review",
                    }
                    reviews[field_name] = "needs_review"
            paper.metadata_provenance = provenance
            paper.metadata_field_reviews = reviews
        repaired: list[str] = []
        for raw_name in paper.authors:
            if is_malformed_author_name(raw_name):
                summary["paper_author_labels_removed"] += 1
                continue
            cleaned = clean_author_name(raw_name)
            identity, _created = ensure_author_identity(session, cleaned, source="paper_author_field")
            canonical_name = identity.canonical_name or identity.name
            if canonical_name != raw_name:
                summary["paper_author_names_normalized"] += 1
            if canonical_name not in repaired:
                repaired.append(canonical_name)
        if repaired != paper.authors:
            paper.authors = repaired
            paper.updated_at = utc_now()
            session.add(paper)

    counts: dict[str, int] = {}
    for paper in session.exec(select(Paper)).all():
        for name in paper.authors:
            counts[name] = counts.get(name, 0) + 1
    for author in session.exec(select(Author)).all():
        if author.identity_status in {"merged", "invalid"}:
            author.paper_count = 0
        else:
            author.paper_count = counts.get(author.canonical_name or author.name, 0)
        author.updated_at = utc_now()
        session.add(author)
    session.commit()
    return summary


def audit_pdf_title_identities(session: Session) -> dict[str, Any]:
    """Audit extracted first pages against metadata titles and persist exclusions."""

    summary: dict[str, Any] = {
        "assessed": 0,
        "matched": 0,
        "possible_mismatch": 0,
        "not_assessed": 0,
        "excluded_paper_ids": [],
    }
    papers = list(
        session.exec(
            select(Paper)
            .where(Paper.extracted_json_path.is_not(None))
            .order_by(Paper.paper_id)
        ).all()
    )
    for paper in papers:
        path = Path(str(paper.extracted_json_path))
        page_texts: list[tuple[int, str]] = []
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                pages = payload.get("pages") if isinstance(payload, dict) else None
                if isinstance(pages, list):
                    page_texts = [
                        (int(page.get("page_number") or index), str(page.get("text") or ""))
                        for index, page in enumerate(pages[:8], start=1)
                        if isinstance(page, dict)
                    ]
            except (OSError, json.JSONDecodeError, AttributeError, TypeError):
                page_texts = []
        diagnostic = title_match_diagnostic_pages(paper.title, page_texts)
        status = str(diagnostic["status"])
        summary["assessed"] += 1
        summary[status] += 1
        paper.pdf_title_match_status = status
        paper.pdf_title_match_score = diagnostic.get("token_coverage")
        extraction_diagnostics = dict(paper.extraction_diagnostics or {})
        extraction_diagnostics["pdf_title_match"] = diagnostic
        paper.extraction_diagnostics = extraction_diagnostics
        if status == "possible_mismatch":
            paper.corpus_eligibility_status = "excluded_pdf_metadata_mismatch"
            paper.corpus_exclusion_reason = diagnostic["reason"]
            paper.review_status = "needs_review"
            summary["excluded_paper_ids"].append(paper.paper_id)
        elif status == "matched" and paper.pdf_text_status == "extracted":
            paper.corpus_eligibility_status = "eligible"
            paper.corpus_exclusion_reason = None
        else:
            paper.corpus_eligibility_status = "needs_review"
            paper.corpus_exclusion_reason = str(diagnostic["reason"])
        paper.updated_at = utc_now()
        session.add(paper)
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair deterministic metadata and author-identity defects.")
    parser.add_argument("command", choices=["repair-authors", "audit-pdf-titles"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    if args.command == "repair-authors":
        with Session(engine) as session:
            print(repair_author_identities(session))
    elif args.command == "audit-pdf-titles":
        with Session(engine) as session:
            print(audit_pdf_title_identities(session))


if __name__ == "__main__":
    main()
