from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Paper

USER_AGENT = "TTLABResearchIntelligence/0.1 (+https://lab.tt)"


@dataclass
class DownloadRecord:
    paper_id: str
    pdf_url: str | None
    local_pdf_path: str | None = None
    pdf_text_status: str | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_direct_pdf_candidate(url: str | None) -> bool:
    if not url:
        return False
    return urlparse(url).path.lower().endswith(".pdf")


def has_acceptable_pdf_content_type(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower().split(";")[0].strip()
    if not content_type:
        return True
    return content_type in {"application/pdf", "application/octet-stream", "binary/octet-stream"}


def has_pdf_signature(content: bytes) -> bool:
    return content.startswith(b"%PDF")


def verify_pdf_response(response: httpx.Response) -> bool:
    return has_acceptable_pdf_content_type(response) and has_pdf_signature(response.content[:1024])


def deterministic_pdf_path(output_dir: Path, paper_id: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in paper_id).strip("-")
    return output_dir / f"{safe_name}.pdf"


def load_records_from_seed(seed_path: Path) -> list[DownloadRecord]:
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Seed file must contain a JSON array.")
    loaded: list[DownloadRecord] = []
    for record in records:
        if not isinstance(record, dict) or not record.get("paper_id"):
            continue
        loaded.append(
            DownloadRecord(
                paper_id=str(record["paper_id"]),
                pdf_url=str(record["pdf_url"]) if record.get("pdf_url") else None,
                local_pdf_path=str(record["local_pdf_path"]) if record.get("local_pdf_path") else None,
                pdf_text_status=str(record["pdf_text_status"]) if record.get("pdf_text_status") else None,
            )
        )
    return loaded


def load_records_from_db(session: Session) -> list[DownloadRecord]:
    papers = session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all()
    return [
        DownloadRecord(
            paper_id=paper.paper_id,
            pdf_url=paper.pdf_url,
            local_pdf_path=paper.local_pdf_path,
            pdf_text_status=paper.pdf_text_status,
        )
        for paper in papers
    ]


def filter_records(
    records: list[DownloadRecord],
    paper_ids: list[str] | None,
    only_missing: bool,
    output_dir: Path,
) -> list[DownloadRecord]:
    allowed = set(paper_ids or [])
    filtered: list[DownloadRecord] = []
    for record in records:
        if allowed and record.paper_id not in allowed:
            continue
        if only_missing:
            target = deterministic_pdf_path(output_dir, record.paper_id)
            if record.local_pdf_path or target.exists():
                continue
        filtered.append(record)
    return filtered


def update_paper_download_status(
    session: Session | None,
    paper_id: str,
    *,
    local_pdf_path: str | None = None,
    ingestion_status: str | None = None,
    pdf_text_status: str | None = None,
) -> None:
    if session is None:
        return
    paper = session.get(Paper, paper_id)
    if paper is None:
        return
    if local_pdf_path is not None:
        paper.local_pdf_path = local_pdf_path
    if ingestion_status is not None:
        paper.ingestion_status = ingestion_status
    if pdf_text_status is not None:
        paper.pdf_text_status = pdf_text_status
    paper.updated_at = utc_now()
    session.add(paper)


def download_pdfs(
    records: list[DownloadRecord],
    output_dir: Path,
    *,
    limit: int | None = None,
    download: bool = False,
    overwrite: bool = False,
    timeout: float = 30.0,
    session: Session | None = None,
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "attempted": 0,
        "downloaded": 0,
        "skipped_existing": 0,
        "failed": 0,
        "invalid_pdf": 0,
        "missing_pdf_url": 0,
    }
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
        timeout=timeout,
        follow_redirects=True,
    )
    try:
        for record in records:
            if limit is not None and summary["attempted"] >= limit:
                break
            if not is_direct_pdf_candidate(record.pdf_url):
                summary["missing_pdf_url"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="missing_pdf",
                    pdf_text_status="missing_pdf",
                )
                continue

            target = deterministic_pdf_path(output_dir, record.paper_id)
            if target.exists() and not overwrite:
                summary["skipped_existing"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    local_pdf_path=str(target),
                    ingestion_status="pdf_downloaded",
                    pdf_text_status="downloaded",
                )
                continue

            summary["attempted"] += 1
            if not download:
                print(f"dry-run would_download paper_id={record.paper_id} url={record.pdf_url} target={target}")
                continue

            try:
                response = client.get(str(record.pdf_url))
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"failed paper_id={record.paper_id} reason={exc}")
                summary["failed"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="download_failed",
                    pdf_text_status="download_failed",
                )
                continue

            if not verify_pdf_response(response):
                print(f"invalid_pdf paper_id={record.paper_id} url={record.pdf_url}")
                summary["invalid_pdf"] += 1
                update_paper_download_status(
                    session,
                    record.paper_id,
                    ingestion_status="invalid_pdf",
                    pdf_text_status="invalid_pdf",
                )
                continue

            target.write_bytes(response.content)
            update_paper_download_status(
                session,
                record.paper_id,
                local_pdf_path=str(target),
                ingestion_status="pdf_downloaded",
                pdf_text_status="downloaded",
            )
            print(f"downloaded paper_id={record.paper_id} target={target}")
            summary["downloaded"] += 1
    finally:
        client.close()
    if session is not None:
        session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely download direct TTLAB PDF URLs.")
    parser.add_argument("--seed", default="data/seed/ttlab_publications_discovered.json")
    parser.add_argument("--from-db", action="store_true", help="Read paper URLs from SQLite instead of seed JSON.")
    parser.add_argument("--out-dir", default="data/pdfs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--paper-id", action="append", default=None)
    parser.add_argument("--download", action="store_true", help="Actually save PDFs. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly keep dry-run behavior.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only-missing", dest="only_missing", action="store_true", default=True)
    parser.add_argument("--include-existing", dest="only_missing", action="store_false")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    output_dir = Path(args.out_dir)
    with Session(engine) as session:
        records = load_records_from_db(session) if args.from_db else load_records_from_seed(Path(args.seed))
        records = filter_records(records, args.paper_id, args.only_missing, output_dir)
        summary = download_pdfs(
            records,
            output_dir,
            limit=args.limit,
            download=bool(args.download and not args.dry_run),
            overwrite=args.overwrite,
            timeout=args.timeout,
            session=session if args.from_db else None,
        )
    print(
        "attempted={attempted} downloaded={downloaded} skipped_existing={skipped_existing} "
        "failed={failed} invalid_pdf={invalid_pdf} missing_pdf_url={missing_pdf_url}".format(**summary)
    )


if __name__ == "__main__":
    main()
