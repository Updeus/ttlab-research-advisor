from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Author, Paper


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

        authors = normalize_list(record.get("authors"))
        pdf_url = record.get("pdf_url")
        local_pdf_path = record.get("local_pdf_path") or record.get("pdf_path")
        pdf_text_status = record.get("pdf_text_status") or ("not_extracted" if pdf_url or local_pdf_path else "missing_pdf")
        if pdf_text_status == "missing_pdf":
            summary["missing_pdf"] += 1

        existing = session.get(Paper, str(paper_id))
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
            "doi": optional_str(record.get("doi")),
            "keywords": normalize_list(record.get("keywords")),
            "topics": normalize_list(record.get("topics")),
            "all_urls": normalize_list(record.get("all_urls")),
            "raw_record": record,
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
    update_author_counts(session)
    return summary


def upsert_author(session: Session, author_name: str) -> bool:
    existing = session.exec(select(Author).where(Author.name == author_name)).first()
    if existing:
        existing.updated_at = utc_now()
        session.add(existing)
        return False
    session.add(Author(name=author_name, review_status="needs_review"))
    return True


def update_author_counts(session: Session) -> None:
    papers = list(session.exec(select(Paper)).all())
    counts: dict[str, int] = {}
    for paper in papers:
        for author_name in paper.authors:
            counts[author_name] = counts.get(author_name, 0) + 1
    for author in session.exec(select(Author)).all():
        author.paper_count = counts.get(author.name, 0)
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
