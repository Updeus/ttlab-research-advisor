#!/usr/bin/env python3
"""Fail loudly on stale, incomplete, or structurally broken manuscript artefacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from manuscript_v2_package import load_manuscript_v2_package


ROOT = Path(__file__).resolve().parents[1]
PAPER_SOURCE = ROOT / "paper" / "ieee-paper.tex"
THESIS_ROOT = ROOT / "thesis"
BIBLIOGRAPHY = THESIS_ROOT / "references.bib"
PAPER_PDF = ROOT / "build" / "ieee-paper.pdf"
THESIS_PDF = ROOT / "build" / "thesis.pdf"
PAPER_MAX_PAGES = 6
THESIS_MIN_PAGES = 75
PAPER_REFERENCE_TARGET = range(18, 23)
PAPER_GENERATED_MACROS = ROOT / "paper" / "generated" / "metrics.tex"
PAPER_GENERATED_MANIFEST = ROOT / "paper" / "generated" / "manifest.json"
THESIS_GENERATED_MACROS = ROOT / "thesis" / "generated" / "evidence_macros.tex"
THESIS_GENERATED_MANIFEST = ROOT / "thesis" / "generated" / "manuscript_metrics_manifest.json"

REQUIRED_V2_MACRO_USAGE = (
    "VTwoEvidenceTier",
    "VTwoPackageStatus",
    "VTwoEvaluationSourceCommitPrefix",
    "VTwoCorpusSnapshotId",
    "VTwoTechnicalEligiblePapers",
    "VTwoTechnicalEligibleChunks",
    "VTwoEvaluationScope",
    "VTwoPublicProjectionExercised",
    "VTwoQATestCases",
    "VTwoQAAnswerabilityPrecision",
    "VTwoQAAnswerabilityPrecisionCi",
    "VTwoQACitationLocatorPrecision",
    "VTwoQACitationLocatorPrecisionCi",
    "VTwoFinderTestProfiles",
    "VTwoFinderHitAtThreeDelta",
    "VTwoFinderHitAtThreeDeltaCi",
    "VTwoTopicTestCases",
    "VTwoTopicKnownPositiveRecall",
    "VTwoTopicKnownPositiveRecallCi",
    "VTwoOCRCharacterErrorRate",
)
PROHIBITED_V2_TOPIC_MACROS = (
    "VTwoTopicMicroPrecision",
    "VTwoTopicMicroFOne",
    "VTwoTopicExactMatch",
)
HAND_ENTERED_V2_RESULT = re.compile(
    r"(?:remediation[-~ ]?v2|peer-review-remediation-v2|\bv2\s+(?:run|evaluation|result))"
    r".{0,180}?(?:\b\d+(?:\.\d+)?\s*\\?%|\b0\.\d{2,}\b|"
    r"[+-]\d+(?:\.\d+)?\s*(?:pp|percentage\s+points?)|"
    r"\b\d+\s+(?:cases?|profiles?|papers?|chunks?|predictions?|fixtures?))",
    re.IGNORECASE | re.DOTALL,
)
PROHIBITED_V2_TOPIC_RESULT = re.compile(
    r"(?:remediation[-~ ]?v2|peer-review-remediation-v2|\bv2\b)"
    r".{0,220}?\btopic.{0,100}?\b(?:precision|f[-_ ]?1|exact[- ]match)\b"
    r"\s*(?:=|was|of|:)\s*\d",
    re.IGNORECASE | re.DOTALL,
)

STALE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("obsolete commit", re.compile(r"713ea5c", re.IGNORECASE)),
    ("obsolete partial-index ratio", re.compile(r"(?:25\s+of\s+756|25/756|25-of-756)", re.IGNORECASE)),
    ("obsolete unknown-section ratio", re.compile(r"(?:249/756|32\.94\\?%)", re.IGNORECASE)),
    ("obsolete backend test count", re.compile(r"\b71\s+(?:passing\s+)?backend tests?\b", re.IGNORECASE)),
    ("temporary performance fallback", re.compile(r"(?:measurement\s+pending|benchmark\s+pending)", re.IGNORECASE)),
)

VISIBLE_PDF_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AUTHOR INPUT REQUIRED", re.compile(r"AUTHOR\s+INPUT\s+REQUIRED", re.IGNORECASE)),
    ("measurement pending", re.compile(r"measurement\s+pending", re.IGNORECASE)),
    ("Benchmark pending", re.compile(r"benchmark\s+pending", re.IGNORECASE)),
)

FONT_ROW_SUFFIX = re.compile(
    r"\s+(?P<embedded>yes|no)\s+(?P<subset>yes|no)\s+(?P<unicode>yes|no)"
    r"\s+(?P<object_number>\d+)\s+(?P<object_generation>\d+)\s*$",
    re.IGNORECASE,
)


def run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def paper_tex_sources() -> list[Path]:
    return sorted((ROOT / "paper").rglob("*.tex"))


def thesis_tex_sources() -> list[Path]:
    return sorted(THESIS_ROOT.rglob("*.tex"))


def tex_sources() -> list[Path]:
    return [*paper_tex_sources(), *thesis_tex_sources()]


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


def citation_keys(text: str) -> list[str]:
    """Return normalized keys from ordinary LaTeX citation commands."""

    keys: list[str] = []
    for citation in re.findall(r"\\cite\{([^}]+)\}", text):
        keys.extend(key.strip() for key in citation.split(",") if key.strip())
    return keys


def manuscript_constraint_errors(
    label: str,
    pages: int,
    *,
    cited_references: int | None = None,
) -> list[str]:
    """Apply the supervisor's hard submission constraints without layout heuristics."""

    errors: list[str] = []
    if label == "paper":
        if pages < 1 or pages > PAPER_MAX_PAGES:
            errors.append(f"paper page count {pages} outside the hard 1-{PAPER_MAX_PAGES} page range")
        if cited_references is not None and cited_references not in PAPER_REFERENCE_TARGET:
            errors.append(
                "paper cited-reference count "
                f"{cited_references} outside the documented "
                f"{min(PAPER_REFERENCE_TARGET)}-{max(PAPER_REFERENCE_TARGET)} target"
            )
    elif label == "thesis" and pages < THESIS_MIN_PAGES:
        errors.append(f"thesis page count {pages} below the hard {THESIS_MIN_PAGES}-page minimum")
    return errors


def _authored_sources(paths: list[Path]) -> list[Path]:
    return [path for path in paths if "generated" not in path.relative_to(ROOT).parts]


def _v2_source_checks(
    errors: list[str],
    manuscript_groups: dict[str, str],
    *,
    allow_v2_not_run: bool,
) -> dict[str, Any]:
    try:
        package = load_manuscript_v2_package(ROOT, allow_not_run=allow_v2_not_run)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        errors.append(f"remediation-v2 package validation failed: {exc}")
        return {"status": "invalid", "completed": False, "layout_only": allow_v2_not_run}

    for label, path in (
        ("paper", PAPER_GENERATED_MACROS),
        ("thesis", THESIS_GENERATED_MACROS),
    ):
        if not path.is_file():
            errors.append(f"{label} generated macro file is missing: {path.relative_to(ROOT)}")
        elif package["macro_text"] not in path.read_text(encoding="utf-8"):
            errors.append(f"{label} generated macros are not bound to the selected v2 package state")

    for label, path in (
        ("paper", PAPER_GENERATED_MANIFEST),
        ("thesis", THESIS_GENERATED_MANIFEST),
    ):
        if not path.is_file():
            errors.append(f"{label} generated manifest is missing: {path.relative_to(ROOT)}")
            continue
        try:
            generated_manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append(f"{label} generated manifest is invalid JSON")
            continue
        recorded = generated_manifest.get("remediation_v2") or {}
        if (
            recorded.get("status") != package["status"]
            or recorded.get("completed") is not package["completed"]
            or recorded.get("layout_only") is not package["layout_only"]
            or recorded.get("manifest_sha256") != package["manifest_sha256"]
            or recorded.get("validation_attestation_sha256")
            != package["validation_attestation_sha256"]
        ):
            errors.append(f"{label} generated manifest has stale remediation-v2 identity")
        recorded_sources = generated_manifest.get("sources") or {}
        for name, identity in package["sources"].items():
            if recorded_sources.get(name) != identity:
                errors.append(f"{label} generated manifest has stale remediation-v2 source: {name}")

    for manuscript, text in manuscript_groups.items():
        for macro_name in REQUIRED_V2_MACRO_USAGE:
            if not re.search(rf"\\{re.escape(macro_name)}\b", text):
                errors.append(f"{manuscript} does not use required v2 macro: {macro_name}")
        lowered = text.casefold()
        for phrase in (
            "ai-silver",
            "historical v1",
            "public projection",
            "human validation",
            "entailment",
        ):
            if phrase not in lowered:
                errors.append(f"{manuscript} omits required v2 evidence boundary wording: {phrase}")
        if HAND_ENTERED_V2_RESULT.search(text):
            errors.append(f"{manuscript} contains a hand-entered remediation-v2 numerical result")
        if PROHIBITED_V2_TOPIC_RESULT.search(text):
            errors.append(
                f"{manuscript} reports prohibited v2 topic precision/F1/exact-match evidence"
            )
        for macro_name in PROHIBITED_V2_TOPIC_MACROS:
            if re.search(rf"\\{re.escape(macro_name)}\b", text):
                errors.append(f"{manuscript} uses prohibited positive-only topic macro: {macro_name}")

    return {
        "status": package["status"],
        "completed": package["completed"],
        "layout_only": package["layout_only"],
        "manifest_sha256": package["manifest_sha256"],
        "validation_attestation_sha256": package["validation_attestation_sha256"],
    }


def source_checks(*, allow_v2_not_run: bool = False) -> tuple[list[str], dict[str, Any]]:
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
    manuscript_groups = {
        "paper": "\n".join(sources[path] for path in _authored_sources(paper_tex_sources())),
        "thesis": "\n".join(sources[path] for path in _authored_sources(thesis_tex_sources())),
    }
    v2_report = _v2_source_checks(
        errors,
        manuscript_groups,
        allow_v2_not_run=allow_v2_not_run,
    )
    labels = re.findall(r"\\label\{((?:fig|tab):[^}]+)\}", combined)
    duplicate_labels = sorted(label for label, count in Counter(labels).items() if count > 1)
    errors.extend(f"duplicate float label: {label}" for label in duplicate_labels)
    for label in sorted(set(labels)):
        reference_pattern = re.compile(
            r"\\(?:ref|[cC]ref|autoref)\{[^}]*\b" + re.escape(label) + r"\b[^}]*\}"
        )
        if not reference_pattern.search(combined):
            errors.append(f"unreferenced float label: {label}")

    all_citation_keys = citation_keys(combined)
    paper_citation_keys = citation_keys(manuscript_groups["paper"])
    bib_text = BIBLIOGRAPHY.read_text(encoding="utf-8")
    bib_keys = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib_text)
    duplicate_bib_keys = sorted(key for key, count in Counter(bib_keys).items() if count > 1)
    errors.extend(f"duplicate bibliography key: {key}" for key in duplicate_bib_keys)
    missing_bib_keys = sorted(set(all_citation_keys) - set(bib_keys))
    errors.extend(f"citation key missing from bibliography: {key}" for key in missing_bib_keys)

    cited_reference_count = len(set(paper_citation_keys))
    errors.extend(
        manuscript_constraint_errors(
            "paper",
            1,
            cited_references=cited_reference_count,
        )
    )

    required_identity = (
        "Jarod Esareesingh",
        "Department of Computing",
        "The University of the West Indies",
        "jarod.esareesingh@my.uwi.edu",
        "Trinidad and Tobago",
    )
    for manuscript, text in manuscript_groups.items():
        for value in required_identity:
            if value not in text:
                errors.append(f"verified author metadata missing from {manuscript}: {value}")
        if re.search(r"\bPort of Spain\b", text, re.IGNORECASE):
            errors.append(f"city must not appear in {manuscript} metadata: Port of Spain")

    return errors, {
        "source_files": len(sources),
        "paper_source_files": len(paper_tex_sources()),
        "thesis_source_files": len(thesis_tex_sources()),
        "float_labels": len(labels),
        "citation_occurrences": len(all_citation_keys),
        "bibliography_entries": len(bib_keys),
        "paper_cited_references": cited_reference_count,
        "remediation_v2": v2_report,
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
    for label, path, required_size in (
        ("paper", PAPER_PDF, "letter"),
        ("thesis", THESIS_PDF, "A4"),
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
        errors.extend(manuscript_constraint_errors(label, pages))
        if required_size.casefold() not in info.get("Page size", "").casefold():
            errors.append(f"{label} page size is not {required_size}: {info.get('Page size', 'missing')}")
        for field in ("Title", "Author", "Subject", "Keywords"):
            if not info.get(field, "").strip():
                errors.append(f"{label} PDF metadata field is empty: {field}")

        text_result = run("pdftotext", str(path), "-")
        if text_result.returncode != 0:
            errors.append(f"pdftotext failed for {label}: {text_result.stderr.strip()}")
        else:
            for description, pattern in VISIBLE_PDF_MARKERS:
                if pattern.search(text_result.stdout):
                    errors.append(f"{label} PDF contains a visible {description} marker")

        fonts = run("pdffonts", str(path))
        if fonts.returncode != 0:
            errors.append(f"pdffonts failed for {label}: {fonts.stderr.strip()}")
        else:
            font_lines = fonts.stdout.splitlines()[2:]
            if any(re.search(r"\bType 3\b", line, re.IGNORECASE) for line in font_lines):
                errors.append(f"{label} PDF contains Type 3 fonts")
            parsed_font_rows = [FONT_ROW_SUFFIX.search(line) for line in font_lines if line.strip()]
            if any(match is None for match in parsed_font_rows):
                errors.append(f"{label} PDF contains an unparseable pdffonts row")
            elif any(match.group("embedded").casefold() == "no" for match in parsed_font_rows if match):
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
    parser.add_argument(
        "--allow-v2-not-run",
        action="store_true",
        help="Allow explicit layout-only v2 placeholders; never valid for final readiness.",
    )
    parser.add_argument("--json-out", type=Path, help="Optional path for a machine-readable report.")
    args = parser.parse_args()

    errors, source_report = source_checks(allow_v2_not_run=args.allow_v2_not_run)
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
