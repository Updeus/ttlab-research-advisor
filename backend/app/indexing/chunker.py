from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, delete, select

from app.db import create_db_and_tables, engine
from app.models import Chunk, Paper

SECTION_ALIASES = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "purpose": "Introduction",
    "problem": "Introduction",
    "problem definition": "Introduction",
    "problem formulation": "Introduction",
    "background": "Literature Review",
    "literature review": "Literature Review",
    "literature survey": "Literature Review",
    "related work": "Literature Review",
    "related works": "Literature Review",
    "related work and contribution": "Literature Review",
    "related work and contributions": "Literature Review",
    "method": "Methodology",
    "methods": "Methodology",
    "methodology": "Methodology",
    "methodology and tools": "Methodology",
    "materials and methods": "Methodology",
    "data": "Methodology",
    "dataset": "Methodology",
    "data description": "Methodology",
    "dataset description": "Methodology",
    "data set description": "Methodology",
    "description of datasets": "Methodology",
    "description of data sets": "Methodology",
    "the proposed approach": "Methodology",
    "proposed approach": "Methodology",
    "clustering heuristic": "Methodology",
    "traditional approach": "Methodology",
    "model description": "Methodology",
    "framework": "Methodology",
    "implementation": "Methodology",
    "experimental setup": "Methodology",
    "experiments": "Methodology",
    "results": "Results",
    "findings": "Results",
    "results and discussion": "Results",
    "results and analysis": "Results",
    "numerical results": "Results",
    "experimental results": "Results",
    "performance results": "Results",
    "performance evaluation": "Results",
    "analysis": "Results",
    "evaluation": "Results",
    "discussion": "Discussion",
    "comparison": "Discussion",
    "limitations": "Discussion",
    "conclusion": "Conclusion",
    "conclusions": "Conclusion",
    "conclusion and future work": "Conclusion",
    "conclusions and future work": "Conclusion",
    "conclusion and recommendations": "Conclusion",
    "conclusions and recommendations": "Conclusion",
    "summary and conclusion": "Conclusion",
    "summary and conclusions": "Conclusion",
    "limitations and future work": "Conclusion",
    "limitations and future directions": "Conclusion",
    "future work": "Conclusion",
    "recommendations": "Conclusion",
    "references": "References",
    "bibliography": "References",
}

# These headings delimit scholarly content but do not map defensibly to one of
# the canonical section labels.  Treating them as explicit Unknown boundaries
# prevents a prior section (especially Abstract or Conclusion) from leaking
# through front/back matter.
UNKNOWN_SECTION_HEADINGS = {
    "abbreviations",
    "acknowledgement",
    "acknowledgements",
    "acknowledgment",
    "acknowledgments",
    "author contributions",
    "conflict of interest",
    "conflicts of interest",
    "contents",
    "copyright material",
    "data availability",
    "declarations",
    "funding",
    "general terms",
    "keywords",
    "preface",
}

SECTION_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?P<number>(?:[IVXLCDM]+|\d+(?:\.\d+)*))"
    r"(?:(?:[.)]+\s*)|(?:\s+))(?P<body>.*)$",
    re.IGNORECASE,
)
LETTER_SUBSECTION_PREFIX_RE = re.compile(r"^\s*[A-Z][.)]\s+", re.IGNORECASE)
HEADING_TRAILING_PUNCTUATION_RE = re.compile(r"[\s:.;\-—–]+$")
FORMULA_OR_CODE_RE = re.compile(r"[=<>∑∏√{}\[\]|]|(?:\+|/|\\){2,}")
NON_HEADING_PREFIX_RE = re.compile(
    r"^(?:table|fig(?:ure)?|algorithm|listing|equation|isbn|issn|doi)\b",
    re.IGNORECASE,
)
UPPERCASE_SECTION_CUE_RE = re.compile(
    r"\b(?:application|approach|architecture|background|challenges|conclusion|"
    r"conformance|design|discussion|evaluation|experiments?|framework|future|"
    r"implementation|introduction|limitations|literature|methodology|methods?|"
    r"problem|purpose|recommendations?|references|related|results?|summary|"
    r"system|technologies|work)\b",
    re.IGNORECASE,
)


def _normalize_heading(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[_\-—–]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _strip_section_number(value: str) -> tuple[str, bool]:
    match = SECTION_NUMBER_PREFIX_RE.match(value)
    if not match:
        return value.strip(), False
    body = match.group("body").strip()
    # A bare Roman/Arabic marker is a real extracted section boundary; the
    # following line normally contains the title.
    return body, True


def _heading_alias(candidate: str, *, numbered: bool) -> str | None:
    """Return a canonical section only for an explicit heading presentation."""

    stripped = HEADING_TRAILING_PUNCTUATION_RE.sub("", candidate).strip()
    normalized = _normalize_heading(stripped)
    if normalized in SECTION_ALIASES:
        # Standalone DATA/DATASET/ANALYSIS/EVALUATION is too ambiguous without
        # a structural marker or all-uppercase typography.  This avoids table
        # headers becoming section changes while supporting observed headings.
        if normalized in {"data", "dataset", "analysis", "evaluation"}:
            if not numbered and not stripped.isupper():
                return None
        return SECTION_ALIASES[normalized]

    # The source corpus contains qualified method headings such as
    # "PROPOSED METHOD FOR DISTRIBUTED COMPUTATION".  Match the semantic head,
    # not arbitrary occurrences of "method" in prose.
    if re.fullmatch(r"proposed (?:method|approach)(?:\s+for\s+[a-z0-9 ]+)?", normalized):
        return "Methodology"
    if re.fullmatch(r"traditional (?:method|approach)(?:\s+for\s+[a-z0-9 ]+)?", normalized):
        return "Methodology"
    if re.fullmatch(r"(?:data|dataset|data set) description(?:\s+and\s+[a-z0-9 ]+)?", normalized):
        return "Methodology"
    return None


def _mapped_heading_with_inline_body(candidate: str, *, numbered: bool) -> str | None:
    """Recognize headings whose body starts on the same extracted line."""

    abstract_match = re.match(r"^(?P<head>abstract)\s+(?P<body>\S.*)$", candidate, flags=re.IGNORECASE)
    if abstract_match:
        original_head = abstract_match.group("head")
        if numbered or original_head.isupper() or original_head[:1].isupper():
            return "Abstract"
    for alias in sorted(SECTION_ALIASES, key=len, reverse=True):
        match = re.match(
            rf"^(?P<head>{re.escape(alias)})(?P<delimiter>\s*[:.\-—–]\s*)(?P<body>\S.*)$",
            candidate,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        original_head = match.group("head")
        # Lowercase prose such as "limitations. We ..." and bibliography text
        # such as "introduction. Comput. Optim." are not heading evidence.
        if not numbered and not (original_head.isupper() or original_head[:1].isupper()):
            return None
        if alias in {"data", "dataset", "analysis", "evaluation"}:
            delimiter = match.group("delimiter").strip()
            if delimiter in {"-", "—", "–"}:
                return None
        return SECTION_ALIASES[alias]
    return None


def _roman_value(value: str) -> int | None:
    if not value or not re.fullmatch(r"[IVXLCDM]+", value, flags=re.IGNORECASE):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for character in reversed(value.upper()):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def _plausible_section_marker(compact: str) -> bool:
    match = SECTION_NUMBER_PREFIX_RE.match(compact)
    if not match:
        return False
    marker = match.group("number")
    if marker[:1].isdigit():
        try:
            return int(marker.split(".", 1)[0]) <= 50
        except ValueError:
            return False
    value = _roman_value(marker)
    return value is not None and value <= 50


def is_strong_section_heading(line: str) -> bool:
    """Detect an explicit but unmapped major heading conservatively.

    Only numbered or all-uppercase lines qualify.  Formulae, table captions,
    single-symbol fragments, and ordinary numbered prose are rejected.
    """

    compact = re.sub(r"\s+", " ", line).strip()
    if not compact or len(compact) > 180:
        return False
    candidate, numbered = _strip_section_number(compact)
    if numbered and not _plausible_section_marker(compact):
        return False
    if numbered and not candidate:
        return True
    if not candidate or NON_HEADING_PREFIX_RE.match(candidate):
        return False
    if LETTER_SUBSECTION_PREFIX_RE.match(compact) or FORMULA_OR_CODE_RE.search(candidate):
        return False
    if ":" in candidate.rstrip(":") or "," in candidate:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", candidate)
    if not words or len(words) > 14:
        return False
    alpha_count = sum(character.isalpha() for character in candidate)
    visible_count = sum(not character.isspace() for character in candidate)
    if not visible_count or alpha_count / visible_count < 0.60:
        return False
    uppercase_heading = (
        candidate.isupper()
        and len(words) >= 2
        and any(len(word) > 1 for word in words)
        and bool(UPPERCASE_SECTION_CUE_RE.search(candidate))
    )
    if not numbered and not uppercase_heading:
        return False
    if numbered and not uppercase_heading:
        title_words = sum(word[:1].isupper() for word in words)
        if title_words / len(words) < 0.70:
            return False
    return True


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
    candidate, numbered = _strip_section_number(compact)
    if not candidate:
        return None
    mapped = _heading_alias(candidate, numbered=numbered)
    if mapped:
        return mapped
    return _mapped_heading_with_inline_body(candidate, numbered=numbered)


def detect_section_boundary(line: str) -> tuple[bool, str | None]:
    """Return whether a line changes section state and its canonical label.

    ``None`` with a true boundary means that the evidence supports a new major
    section, but not one of the canonical labels.  Callers must reset to
    ``Unknown`` instead of carrying the previous label forward.
    """

    compact = re.sub(r"\s+", " ", line).strip()
    if not compact:
        return False, None
    section = detect_section_heading(compact)
    if section:
        return True, section
    candidate, _ = _strip_section_number(compact)
    normalized = _normalize_heading(HEADING_TRAILING_PUNCTUATION_RE.sub("", candidate))
    if normalized in UNKNOWN_SECTION_HEADINGS or is_strong_section_heading(compact):
        return True, None
    return False, None


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
    substantive_section_seen = False
    for page in extracted.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        page_text = str(page.get("text") or "")
        lines = [line.strip() for line in page_text.splitlines() if line.strip()] or [page_text]
        for line in lines:
            boundary, detected = detect_section_boundary(line)
            # Two-column extraction can place an Abstract block after the
            # Introduction/Related Work lines from the opposite column.  Once
            # substantive body evidence has appeared, do not relabel that body
            # as Abstract merely because the extraction order is interleaved.
            if detected == "Abstract" and substantive_section_seen:
                boundary = False
                detected = None
            if boundary:
                current_section = detected or "Unknown"
                if detected not in {None, "Abstract"}:
                    substantive_section_seen = True
            for sentence in split_sentences(line):
                units.append(
                    {
                        "text": sentence,
                        "page_number": page_number,
                        "word_count": count_words(sentence),
                        "section_hint": current_section,
                        "section_heading_detected": detected,
                        "section_boundary_detected": boundary,
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
