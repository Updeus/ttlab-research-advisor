#!/usr/bin/env python3
"""Fail loudly on stale, incomplete, or structurally broken manuscript artefacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAPER_SOURCE = ROOT / "paper" / "ieee-paper.tex"
THESIS_ROOT = ROOT / "thesis"
BIBLIOGRAPHY = THESIS_ROOT / "references.bib"
PAPER_PDF = ROOT / "build" / "ieee-paper.pdf"
THESIS_PDF = ROOT / "build" / "thesis.pdf"

STALE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("obsolete commit", re.compile(r"713ea5c", re.IGNORECASE)),
    ("obsolete partial-index ratio", re.compile(r"(?:25\s+of\s+756|25/756|25-of-756)", re.IGNORECASE)),
    ("obsolete unknown-section ratio", re.compile(r"(?:249/756|32\.94\\?%)", re.IGNORECASE)),
    ("obsolete backend test count", re.compile(r"\b71\s+(?:passing\s+)?backend tests?\b", re.IGNORECASE)),
)


def run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def tex_sources() -> list[Path]:
    return [PAPER_SOURCE, *sorted(THESIS_ROOT.rglob("*.tex"))]


def read_sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in tex_sources()}


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def add_match_errors(
    errors: list[str],
    sources: dict[Path, str],
    description: str,
    pattern: re.Pattern[str],
) -> None:
    for path, text in sources.items():
        for match in pattern.finditer(text):
            errors.append(f"{path.relative_to(ROOT)}:{line_number(text, match.start())}: {description}")


def source_checks() -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    sources = read_sources()

    for path, text in sources.items():
        for match in re.finditer(r"\\authorinput\s*\{", text):
            prefix = text[max(0, match.start() - 40) : match.start()]
            if "newcommand" not in prefix:
                errors.append(
                    f"{path.relative_to(ROOT)}:{line_number(text, match.start())}: "
                    "visible author-input macro remains"
                )
        for match in re.finditer(r"AUTHOR INPUT REQUIRED", text, re.IGNORECASE):
            line = text.splitlines()[line_number(text, match.start()) - 1]
            if "newcommand" not in line:
                errors.append(
                    f"{path.relative_to(ROOT)}:{line_number(text, match.start())}: "
                    "literal author-input marker remains"
                )

    for description, pattern in STALE_PATTERNS:
        add_match_errors(errors, sources, description, pattern)

    combined = "\n".join(sources.values())
    labels = re.findall(r"\\label\{((?:fig|tab):[^}]+)\}", combined)
    duplicate_labels = sorted(label for label, count in Counter(labels).items() if count > 1)
    errors.extend(f"duplicate float label: {label}" for label in duplicate_labels)
    for label in sorted(set(labels)):
        reference_pattern = re.compile(
            r"\\(?:ref|[cC]ref|autoref)\{[^}]*\b" + re.escape(label) + r"\b[^}]*\}"
        )
        if not reference_pattern.search(combined):
            errors.append(f"unreferenced float label: {label}")

    citation_keys: list[str] = []
    for citation in re.findall(r"\\cite\{([^}]+)\}", combined):
        citation_keys.extend(key.strip() for key in citation.split(",") if key.strip())
    bib_text = BIBLIOGRAPHY.read_text(encoding="utf-8")
    bib_keys = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib_text)
    duplicate_bib_keys = sorted(key for key, count in Counter(bib_keys).items() if count > 1)
    errors.extend(f"duplicate bibliography key: {key}" for key in duplicate_bib_keys)
    missing_bib_keys = sorted(set(citation_keys) - set(bib_keys))
    errors.extend(f"citation key missing from bibliography: {key}" for key in missing_bib_keys)

    required_identity = (
        "Jarod Esareesingh",
        "Department of Computing",
        "The University of the West Indies",
        "jarod.esareesingh@my.uwi.edu",
        "Trinidad and Tobago",
    )
    for value in required_identity:
        if value not in combined:
            errors.append(f"verified author metadata missing: {value}")
    if re.search(r"\bPort of Spain\b", combined, re.IGNORECASE):
        errors.append("city must not appear in manuscript metadata: Port of Spain")

    return errors, {
        "source_files": len(sources),
        "float_labels": len(labels),
        "citation_occurrences": len(citation_keys),
        "bibliography_entries": len(bib_keys),
    }


def parse_pdfinfo(path: Path) -> dict[str, str]:
    completed = run("pdfinfo", str(path))
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"pdfinfo failed for {path}")
    result: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def pdf_checks() -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    report: dict[str, Any] = {}
    for label, path, page_range, required_size in (
        ("paper", PAPER_PDF, range(6, 9), "letter"),
        ("thesis", THESIS_PDF, range(40, 501), "A4"),
    ):
        if not path.exists():
            errors.append(f"missing compiled PDF: {path.relative_to(ROOT)}")
            continue
        try:
            info = parse_pdfinfo(path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        report[label] = info
        try:
            pages = int(info.get("Pages", "0"))
        except ValueError:
            pages = 0
        if pages not in page_range:
            errors.append(
                f"{label} page count {pages} outside required "
                f"{min(page_range)}-{max(page_range)}"
            )
        if required_size.casefold() not in info.get("Page size", "").casefold():
            errors.append(f"{label} page size is not {required_size}: {info.get('Page size', 'missing')}")
        for field in ("Title", "Author", "Subject", "Keywords"):
            if not info.get(field, "").strip():
                errors.append(f"{label} PDF metadata field is empty: {field}")

        text_result = run("pdftotext", str(path), "-")
        if text_result.returncode != 0:
            errors.append(f"pdftotext failed for {label}: {text_result.stderr.strip()}")
        elif "AUTHOR INPUT REQUIRED" in text_result.stdout.upper():
            errors.append(f"{label} PDF contains a visible AUTHOR INPUT REQUIRED marker")

        fonts = run("pdffonts", str(path))
        if fonts.returncode != 0:
            errors.append(f"pdffonts failed for {label}: {fonts.stderr.strip()}")
        else:
            font_lines = fonts.stdout.splitlines()[2:]
            if any(re.search(r"\bType 3\b", line, re.IGNORECASE) for line in font_lines):
                errors.append(f"{label} PDF contains Type 3 fonts")
            if any(re.search(r"\bno\s+no\s*$", line, re.IGNORECASE) for line in font_lines):
                errors.append(f"{label} PDF contains an unembedded font")

        log_path = ROOT / "build" / ("ieee-paper.log" if label == "paper" else "thesis.log")
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            for pattern, description in (
                (r"Citation [`'][^\n]+ undefined", "undefined citation"),
                (r"Reference [`'][^\n]+ undefined", "undefined reference"),
                (r"There were undefined references", "undefined references summary"),
            ):
                if re.search(pattern, log_text, re.IGNORECASE):
                    errors.append(f"{label} build log contains {description}")
            overfull = [float(value) for value in re.findall(r"Overfull \\hbox \(([0-9.]+)pt too wide\)", log_text)]
            if overfull and max(overfull) > 1.0:
                errors.append(f"{label} build log has overfull box wider than 1 pt: {max(overfull):.3f} pt")

    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="Skip compiled-PDF checks.")
    parser.add_argument("--json-out", type=Path, help="Optional path for a machine-readable report.")
    args = parser.parse_args()

    errors, source_report = source_checks()
    pdf_report: dict[str, Any] = {}
    if not args.source_only:
        pdf_errors, pdf_report = pdf_checks()
        errors.extend(pdf_errors)
    payload = {
        "status": "PASS" if not errors else "FAIL",
        "source": source_report,
        "pdf": pdf_report,
        "errors": errors,
    }
    if args.json_out:
        output = args.json_out if args.json_out.is_absolute() else ROOT / args.json_out
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
