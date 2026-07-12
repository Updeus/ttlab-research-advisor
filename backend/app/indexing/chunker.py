from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, delete, select

from app.db import create_db_and_tables, engine
from app.models import Chunk, Paper

SECTION_ALIASES = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "background": "Literature Review",
    "literature review": "Literature Review",
    "related work": "Literature Review",
    "method": "Methodology",
    "methods": "Methodology",
    "methodology": "Methodology",
    "materials and methods": "Methodology",
    "experimental setup": "Methodology",
    "results": "Results",
    "findings": "Results",
    "results and discussion": "Results",
    "discussion": "Discussion",
    "limitations": "Discussion",
    "conclusion": "Conclusion",
    "conclusions": "Conclusion",
    "conclusion and future work": "Conclusion",
    "limitations and future work": "Conclusion",
    "future work": "Conclusion",
    "references": "References",
    "bibliography": "References",
}
SECTION_HEADING_RE = re.compile(
    r"^\s*(?:(?:[IVXLCDM]+|\d+(?:\.\d+)*)[.)]?\s+)?"
    r"(?P<heading>abstract|introduction|background|literature review|related work|"
    r"methods?|methodology|materials and methods|experimental setup|results?|findings|"
    r"results and discussion|discussion|limitations|conclusions?|conclusion and future work|"
    r"limitations and future work|future work|references|bibliography)"
    r"\s*(?P<suffix>[:.\-—]?)(?P<rest>.*)$",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def count_words(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_chunk_id(paper_id: str, chunk_index: int, page_start: int | None, page_end: int | None, chunk_hash: str) -> str:
    digest = hashlib.sha1(f"{paper_id}|{chunk_index}|{page_start}|{page_end}|{chunk_hash}".encode("utf-8")).hexdigest()[:12]
    return f"{paper_id}-chunk-{chunk_index:04d}-{digest}"


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", normalized)
    return [piece.strip() for piece in pieces if piece.strip()]


def detect_section_heading(line: str) -> str | None:
    compact = re.sub(r"\s+", " ", line).strip()
    if not compact or len(compact) > 240:
        return None
    match = SECTION_HEADING_RE.match(compact)
    if not match:
        return None
    heading = re.sub(r"\s+", " ", match.group("heading").casefold()).strip()
    rest = match.group("rest").strip()
    suffix = match.group("suffix")
    # A heading embedded in ordinary prose is deliberately left Unknown. Abstract
    # commonly starts its body on the same extracted line; numbered/uppercase
    # headings and punctuation-delimited headings are also accepted.
    heading_token = match.group("heading")
    prefix = compact[: match.start("heading")]
    defensible_prefix = bool(prefix.strip()) or heading_token.isupper() or bool(suffix)
    if rest and heading != "abstract" and not defensible_prefix:
        return None
    return SECTION_ALIASES.get(heading)


def infer_section(text: str) -> str:
    head = text[:1200]
    for line in head.splitlines() or [head]:
        section = detect_section_heading(line)
        if section:
            return section
    # Chunk assembly normalizes line breaks. Permit only a heading at the very
    # beginning, never a keyword appearing later in prose.
    section = detect_section_heading(head[:240])
    if section:
        return section
    return "Unknown"


def page_sentence_units(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    current_section: str | None = None
    for page in extracted.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        page_text = str(page.get("text") or "")
        lines = [line.strip() for line in page_text.splitlines() if line.strip()] or [page_text]
        for line in lines:
            detected = detect_section_heading(line)
            if detected:
                current_section = detected
            for sentence in split_sentences(line):
                units.append(
                    {
                        "text": sentence,
                        "page_number": page_number,
                        "word_count": count_words(sentence),
                        "section_hint": current_section,
                        "section_heading_detected": detected,
                    }
                )
    return units


def overlap_start_index(units: list[dict[str, Any]], start: int, end: int, overlap_words: int) -> int:
    words = 0
    index = end - 1
    while index > start and words < overlap_words:
        words += int(units[index]["word_count"])
        index -= 1
    return max(start + 1, index + 1)


def build_chunks_from_extraction(
    extracted: dict[str, Any],
    *,
    target_words: int = 850,
    max_chars: int = 5000,
    overlap_words: int = 125,
    min_chars: int = 400,
) -> list[dict[str, Any]]:
    paper_id = str(extracted["paper_id"])
    units = page_sentence_units(extracted)
    chunks: list[dict[str, Any]] = []
    index = 0
    while index < len(units):
        chunk_units: list[dict[str, Any]] = []
        words = 0
        chars = 0
        end = index
        while end < len(units):
            unit = units[end]
            next_chars = chars + len(unit["text"]) + 1
            if chunk_units and (words >= target_words or next_chars > max_chars):
                break
            chunk_units.append(unit)
            words += int(unit["word_count"])
            chars = next_chars
            end += 1
        chunk = make_chunk_record(paper_id, len(chunks), chunk_units)
        chunks.append(chunk)
        if end >= len(units):
            break
        index = overlap_start_index(units, index, end, overlap_words)

    if len(chunks) > 1 and chunks[-1]["char_count"] < min_chars:
        final = chunks.pop()
        previous = chunks.pop()
        merged_units = [
            {
                "text": sentence,
                "page_number": previous["page_start"],
                "word_count": count_words(sentence),
                "section_hint": previous.get("section"),
            }
            for sentence in split_sentences(previous["text"])
        ]
        merged_units.extend(
            {
                "text": sentence,
                "page_number": final["page_start"],
                "word_count": count_words(sentence),
                "section_hint": final.get("section"),
            }
            for sentence in split_sentences(final["text"])
        )
        chunks.append(make_chunk_record(paper_id, len(chunks), merged_units))

    for chunk_index, chunk in enumerate(chunks):
        chunk["chunk_index"] = chunk_index
        chunk["chunk_id"] = stable_chunk_id(
            paper_id,
            chunk_index,
            chunk["page_start"],
            chunk["page_end"],
            chunk["source_hash"],
        )
    return chunks


def make_chunk_record(paper_id: str, chunk_index: int, units: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(unit["text"] for unit in units).strip()
    pages = [int(unit["page_number"]) for unit in units if int(unit["page_number"]) > 0]
    words = count_words(text)
    chunk_hash = source_hash(text)
    section_weights: dict[str, int] = {}
    for unit in units:
        hint = unit.get("section_hint")
        if hint:
            section_weights[str(hint)] = section_weights.get(str(hint), 0) + int(unit.get("word_count") or 0)
    section = max(section_weights.items(), key=lambda item: item[1])[0] if section_weights else infer_section(text)
    return {
        "chunk_id": stable_chunk_id(paper_id, chunk_index, min(pages) if pages else None, max(pages) if pages else None, chunk_hash),
        "paper_id": paper_id,
        "chunk_index": chunk_index,
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "section": section,
        "text": text,
        "char_count": len(text),
        "word_count": words,
        "token_count_estimate": int(words * 1.3),
        "source_hash": chunk_hash,
    }


def write_chunks(chunks: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def persist_chunks(session: Session, paper: Paper, chunks: list[dict[str, Any]], *, overwrite: bool = False) -> None:
    existing = session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).first()
    if existing and overwrite:
        session.exec(delete(Chunk).where(Chunk.paper_id == paper.paper_id))
    elif existing:
        return
    for chunk in chunks:
        session.add(
            Chunk(
                chunk_id=str(chunk["chunk_id"]),
                paper_id=str(chunk["paper_id"]),
                chunk_index=int(chunk["chunk_index"]),
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                section=str(chunk["section"]),
                text=str(chunk["text"]),
                char_count=int(chunk["char_count"]),
                word_count=int(chunk["word_count"]),
                token_count=int(chunk["token_count_estimate"]),
                token_count_estimate=int(chunk["token_count_estimate"]),
                source_hash=str(chunk["source_hash"]),
            )
        )
    paper.chunk_count = len(chunks)
    paper.updated_at = utc_now()
    session.add(paper)


def candidate_papers(session: Session, paper_ids: list[str] | None = None) -> list[Paper]:
    papers = list(
        session.exec(
            select(Paper)
            .where(Paper.pdf_text_status == "extracted")
            .where(Paper.extracted_json_path.is_not(None))
            .order_by(Paper.year.desc(), Paper.title)
        ).all()
    )
    if paper_ids:
        allowed = set(paper_ids)
        papers = [paper for paper in papers if paper.paper_id in allowed]
    return papers


def chunk_from_db(
    session: Session,
    *,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    overwrite: bool = False,
    min_chars: int = 400,
    output_dir: Path = Path("data/chunks"),
) -> dict[str, int]:
    summary = {"attempted": 0, "chunked": 0, "skipped_existing": 0, "no_text": 0, "failed": 0}
    for paper in candidate_papers(session, paper_ids):
        if limit is not None and summary["attempted"] >= limit:
            break
        output_path = output_dir / f"{paper.paper_id}.json"
        existing_chunk = session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).first()
        if output_path.exists() and existing_chunk and not overwrite:
            summary["skipped_existing"] += 1
            continue
        summary["attempted"] += 1
        if not paper.extracted_json_path or not Path(paper.extracted_json_path).exists():
            summary["failed"] += 1
            continue
        extracted = json.loads(Path(paper.extracted_json_path).read_text(encoding="utf-8"))
        chunks = build_chunks_from_extraction(extracted, min_chars=min_chars)
        if not chunks:
            summary["no_text"] += 1
            paper.chunk_count = 0
            session.add(paper)
            continue
        write_chunks(chunks, output_path)
        persist_chunks(session, paper, chunks, overwrite=overwrite)
        summary["chunked"] += 1
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create deterministic page-aware chunks from extracted text.")
    subparsers = parser.add_subparsers(dest="command")
    chunk = subparsers.add_parser("chunk")
    chunk.add_argument("--limit", type=int, default=None)
    chunk.add_argument("--paper-id", action="append", default=None)
    chunk.add_argument("--overwrite", action="store_true")
    chunk.add_argument("--min-chars", type=int, default=400)
    chunk.add_argument("--out-dir", default="data/chunks")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "chunk":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        summary = chunk_from_db(
            session,
            limit=args.limit,
            paper_ids=args.paper_id,
            overwrite=args.overwrite,
            min_chars=args.min_chars,
            output_dir=Path(args.out_dir),
        )
    print(
        "attempted={attempted} chunked={chunked} skipped_existing={skipped_existing} "
        "no_text={no_text} failed={failed}".format(**summary)
    )


if __name__ == "__main__":
    main()
