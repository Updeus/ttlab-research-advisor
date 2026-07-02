from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Paper


def utc_now() -> datetime:
    return datetime.now(UTC)


def count_words(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_pdf_text(
    paper_id: str,
    local_pdf_path: Path,
    output_dir: Path = Path("data/extracted_text"),
    overwrite: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{paper_id}.json"
    txt_path = output_dir / f"{paper_id}.txt"
    if json_path.exists() and txt_path.exists() and not overwrite:
        return json.loads(json_path.read_text(encoding="utf-8"))

    warnings: list[str] = []
    try:
        document = fitz.open(local_pdf_path)
    except Exception as exc:
        return build_failed_result(paper_id, local_pdf_path, json_path, txt_path, str(exc))

    pages: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    extraction_error: str | None = None
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            normalized_text = text.strip()
            page_record = {
                "page_number": index,
                "text": normalized_text,
                "char_count": len(normalized_text),
                "word_count": count_words(normalized_text),
            }
            pages.append(page_record)
            full_text_parts.append(f"\n\n--- Page {index} ---\n{normalized_text}".strip())
    except Exception as exc:
        extraction_error = str(exc)
    finally:
        document.close()

    full_text = "\n\n".join(part for part in full_text_parts if part)
    total_char_count = sum(page["char_count"] for page in pages)
    total_word_count = sum(page["word_count"] for page in pages)
    pages_with_text = sum(1 for page in pages if page["char_count"] > 0)
    pages_without_text = len(pages) - pages_with_text
    possible_scanned_pdf = len(pages) > 0 and (pages_with_text == 0 or total_word_count < max(25, len(pages) * 5))
    if possible_scanned_pdf:
        warnings.append("PDF may be scanned or image-heavy; little extractable text was found.")

    extraction_status = "failed" if extraction_error else "extracted"
    if not extraction_error and total_char_count == 0:
        extraction_status = "no_text"

    result = {
        "paper_id": paper_id,
        "local_pdf_path": str(local_pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "full_text_path": str(txt_path),
        "text_hash": text_hash(full_text),
        "extraction_status": extraction_status,
        "warnings": warnings,
        "diagnostics": {
            "page_count": len(pages),
            "total_char_count": total_char_count,
            "total_word_count": total_word_count,
            "pages_with_text": pages_with_text,
            "pages_without_text": pages_without_text,
            "possible_scanned_pdf": possible_scanned_pdf,
            "extraction_error": extraction_error,
        },
    }
    txt_path.write_text(full_text + ("\n" if full_text else ""), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def build_failed_result(
    paper_id: str,
    local_pdf_path: Path,
    json_path: Path,
    txt_path: Path,
    error: str,
) -> dict[str, Any]:
    result = {
        "paper_id": paper_id,
        "local_pdf_path": str(local_pdf_path),
        "page_count": 0,
        "pages": [],
        "full_text_path": str(txt_path),
        "text_hash": text_hash(""),
        "extraction_status": "failed",
        "warnings": [],
        "diagnostics": {
            "page_count": 0,
            "total_char_count": 0,
            "total_word_count": 0,
            "pages_with_text": 0,
            "pages_without_text": 0,
            "possible_scanned_pdf": False,
            "extraction_error": error,
        },
    }
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    txt_path.write_text("", encoding="utf-8")
    return result


def update_paper_from_extraction(session: Session, paper: Paper, result: dict[str, Any], json_path: Path) -> None:
    diagnostics = dict(result.get("diagnostics", {}))
    diagnostics["warnings"] = result.get("warnings", [])
    status = result.get("extraction_status")
    paper.pdf_text_status = {
        "extracted": "extracted",
        "no_text": "no_text",
        "failed": "extraction_failed",
    }.get(str(status), "extraction_failed")
    paper.ingestion_status = "text_extracted" if paper.pdf_text_status == "extracted" else paper.pdf_text_status
    paper.extracted_json_path = str(json_path)
    paper.extracted_text_path = str(result.get("full_text_path") or "")
    paper.extraction_diagnostics = diagnostics
    paper.page_count = int(diagnostics.get("page_count") or 0)
    paper.total_char_count = int(diagnostics.get("total_char_count") or 0)
    paper.total_word_count = int(diagnostics.get("total_word_count") or 0)
    paper.pages_with_text = int(diagnostics.get("pages_with_text") or 0)
    paper.pages_without_text = int(diagnostics.get("pages_without_text") or 0)
    paper.possible_scanned_pdf = bool(diagnostics.get("possible_scanned_pdf") or False)
    paper.updated_at = utc_now()
    session.add(paper)


def candidate_papers(session: Session, paper_ids: list[str] | None = None) -> list[Paper]:
    statement = select(Paper).where(Paper.local_pdf_path.is_not(None)).order_by(Paper.year.desc(), Paper.title)
    papers = list(session.exec(statement).all())
    if paper_ids:
        allowed = set(paper_ids)
        papers = [paper for paper in papers if paper.paper_id in allowed]
    return papers


def extract_from_db(
    session: Session,
    *,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    overwrite: bool = False,
    output_dir: Path = Path("data/extracted_text"),
) -> dict[str, int]:
    summary = {"attempted": 0, "extracted": 0, "no_text": 0, "failed": 0, "missing_pdf": 0, "skipped_existing": 0}
    for paper in candidate_papers(session, paper_ids):
        if limit is not None and summary["attempted"] >= limit:
            break
        if not paper.local_pdf_path:
            summary["missing_pdf"] += 1
            continue
        local_pdf_path = Path(paper.local_pdf_path)
        if not local_pdf_path.exists():
            summary["missing_pdf"] += 1
            paper.pdf_text_status = "missing_pdf"
            session.add(paper)
            continue
        json_path = output_dir / f"{paper.paper_id}.json"
        if json_path.exists() and not overwrite and paper.pdf_text_status in {"extracted", "no_text"}:
            summary["skipped_existing"] += 1
            continue
        summary["attempted"] += 1
        result = extract_pdf_text(paper.paper_id, local_pdf_path, output_dir, overwrite=overwrite)
        update_paper_from_extraction(session, paper, result, json_path)
        status = result["extraction_status"]
        if status == "extracted":
            summary["extracted"] += 1
        elif status == "no_text":
            summary["no_text"] += 1
        else:
            summary["failed"] += 1
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract page-aware text from downloaded PDFs.")
    subparsers = parser.add_subparsers(dest="command")
    extract = subparsers.add_parser("extract")
    extract.add_argument("--limit", type=int, default=None)
    extract.add_argument("--paper-id", action="append", default=None)
    extract.add_argument("--overwrite", action="store_true")
    extract.add_argument("--from-db", action="store_true", default=True)
    extract.add_argument("--out-dir", default="data/extracted_text")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "extract":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        summary = extract_from_db(
            session,
            limit=args.limit,
            paper_ids=args.paper_id,
            overwrite=args.overwrite,
            output_dir=Path(args.out_dir),
        )
    print(
        "attempted={attempted} extracted={extracted} no_text={no_text} failed={failed} "
        "missing_pdf={missing_pdf} skipped_existing={skipped_existing}".format(**summary)
    )


if __name__ == "__main__":
    main()
