from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Author, Paper
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
    summary = {"created": 0, "updated": 0, "skipped": 0, "missing_pdf": 0, "authors": 0}
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
        pdf_url = record.get("pdf_url")
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
            "source_url": optional_str(record.get("source_url")),
            "post_url": optional_str(record.get("post_url")),
            "pdf_url": optional_str(pdf_url),
            "local_pdf_path": optional_str(local_pdf_path),
            "pdf_unavailability_reason": pdf_unavailability_reason,
            "pdf_unavailability_detail": pdf_unavailability_detail,
            "doi": optional_str(record.get("doi")),
            "keywords": normalize_list(record.get("keywords")),
            "topics": normalize_list(record.get("topics")),
            "all_urls": normalize_list(record.get("all_urls")),
            "raw_record": record,
            "metadata_provenance": provenance,
            "metadata_field_reviews": field_reviews,
            "ingestion_status": str(record.get("ingestion_status") or "discovered"),
            "pdf_text_status": str(pdf_text_status),
            "review_status": "needs_review",
            "updated_at": utc_now(),
        }

        if existing is None:
            session.add(Paper(paper_id=str(paper_id), **values))
            summary["created"] += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
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
