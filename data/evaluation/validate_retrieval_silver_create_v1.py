#!/usr/bin/env python3
"""Validate the first-pass AI-reviewed retrieval set without running retrieval."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data/evaluation/retrieval_silver_create_v1.jsonl"
DEFAULT_DATABASE = ROOT / "data/papers.db"

CATEGORY_TARGETS = {
    "exact_factual_lookup": 5,
    "methods": 5,
    "results": 5,
    "limitations_future_work": 5,
    "title_author_venue": 5,
    "topic_application": 5,
    "comparison": 4,
    "broad_intent": 4,
    "multi_paper_synthesis": 4,
    "hard_negative": 4,
    "unanswerable_out_of_corpus": 4,
}
EXCLUDED_MISMATCHED_PAPERS = {
    "vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8",
    "pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f",
}
REQUIRED_KEYS = {
    "case_id",
    "question",
    "category",
    "answerability",
    "relevant_paper_ids",
    "supporting_evidence",
    "distractor_paper_ids",
    "rationale",
    "split",
    "reviewer_id",
    "reviewer_type",
    "label_quality",
    "pass",
    "timestamp",
    "annotation_uncertainty",
    "second_pass_note",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser.parse_args()


def load_cases(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    cases: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            errors.append(f"line {line_number}: blank lines are not allowed in JSONL")
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_number}: each JSONL value must be an object")
            continue
        value["_line_number"] = line_number
        cases.append(value)
    return cases, errors


def validate_structure(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    questions: set[str] = set()
    for case in cases:
        line = case["_line_number"]
        case_id = str(case.get("case_id", f"line-{line}"))
        missing = sorted(REQUIRED_KEYS - case.keys())
        if missing:
            errors.append(f"{case_id}: missing keys: {', '.join(missing)}")
        if case_id in ids:
            errors.append(f"{case_id}: duplicate case_id")
        ids.add(case_id)
        question = case.get("question")
        if not isinstance(question, str) or len(question.strip()) < 10:
            errors.append(f"{case_id}: question must be a non-trivial string")
        elif question.casefold() in questions:
            errors.append(f"{case_id}: duplicate question")
        else:
            questions.add(question.casefold())
        if case.get("category") not in CATEGORY_TARGETS:
            errors.append(f"{case_id}: unsupported category {case.get('category')!r}")
        if case.get("split") not in {"dev", "test"}:
            errors.append(f"{case_id}: split must be dev or test")
        if case.get("reviewer_id") != "codex-ai-review" or case.get("reviewer_type") != "ai":
            errors.append(f"{case_id}: reviewer must be codex-ai-review with reviewer_type=ai")
        if case.get("label_quality") != "silver" or case.get("pass") != "create":
            errors.append(f"{case_id}: label_quality/pass must be silver/create")
        if case.get("annotation_uncertainty") not in {"low", "medium", "high"}:
            errors.append(f"{case_id}: invalid annotation_uncertainty")
        timestamp = case.get("timestamp")
        try:
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{case_id}: invalid ISO timestamp {timestamp!r}")
        relevant = case.get("relevant_paper_ids")
        evidence = case.get("supporting_evidence")
        distractors = case.get("distractor_paper_ids")
        if not isinstance(relevant, list) or len(relevant) != len(set(relevant)):
            errors.append(f"{case_id}: relevant_paper_ids must be a unique list")
            relevant = []
        if not isinstance(evidence, list):
            errors.append(f"{case_id}: supporting_evidence must be a list")
            evidence = []
        if not isinstance(distractors, list) or len(distractors) != len(set(distractors)):
            errors.append(f"{case_id}: distractor_paper_ids must be a unique list")
            distractors = []
        if set(relevant) & set(distractors):
            errors.append(f"{case_id}: relevant and distractor paper IDs must be disjoint")
        evidence_paper_ids = {
            item.get("paper_id") for item in evidence if isinstance(item, dict)
        }
        excluded = (
            set(relevant) | set(distractors) | evidence_paper_ids
        ) & EXCLUDED_MISMATCHED_PAPERS
        if excluded:
            errors.append(f"{case_id}: references known title/PDF mismatch records: {sorted(excluded)}")
        if case.get("answerability") == "answerable":
            if not relevant or not evidence:
                errors.append(f"{case_id}: answerable cases require relevant papers and evidence")
            evidenced_papers = {item.get("paper_id") for item in evidence if isinstance(item, dict)}
            missing_evidence = set(relevant) - evidenced_papers
            if missing_evidence:
                errors.append(f"{case_id}: relevant papers without evidence: {sorted(missing_evidence)}")
        elif case.get("answerability") == "unanswerable":
            if relevant or evidence:
                errors.append(f"{case_id}: unanswerable cases must have empty relevant papers and evidence")
            check = case.get("corpus_absence_check")
            if not isinstance(check, dict) or not check.get("terms"):
                errors.append(f"{case_id}: unanswerable case requires corpus_absence_check terms")
        else:
            errors.append(f"{case_id}: invalid answerability {case.get('answerability')!r}")
    return errors


def validate_database(cases: list[dict[str, Any]], database: Path) -> list[str]:
    errors: list[str] = []
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        papers = {
            row["paper_id"]: row
            for row in connection.execute("SELECT paper_id, title, authors, year, venue FROM paper")
        }
        chunks = {
            row["chunk_id"]: row
            for row in connection.execute(
                "SELECT chunk_id, paper_id, page_start, page_end, section, source_hash FROM chunk"
            )
        }
        for case in cases:
            case_id = case.get("case_id", f"line-{case['_line_number']}")
            for paper_id in case.get("relevant_paper_ids", []) + case.get("distractor_paper_ids", []):
                if paper_id not in papers:
                    errors.append(f"{case_id}: unknown paper_id {paper_id}")
            for evidence in case.get("supporting_evidence", []):
                if not isinstance(evidence, dict):
                    errors.append(f"{case_id}: evidence entry is not an object")
                    continue
                chunk_id = evidence.get("chunk_id")
                chunk = chunks.get(chunk_id)
                if chunk is None:
                    errors.append(f"{case_id}: unknown chunk_id {chunk_id}")
                    continue
                for field in ("paper_id", "page_start", "page_end", "section", "source_hash"):
                    if evidence.get(field) != chunk[field]:
                        errors.append(
                            f"{case_id}: {chunk_id} {field} mismatch: "
                            f"dataset={evidence.get(field)!r} db={chunk[field]!r}"
                        )
                if not isinstance(evidence.get("evidence_summary"), str) or len(evidence["evidence_summary"].strip()) < 10:
                    errors.append(f"{case_id}: evidence_summary is missing or too short for {chunk_id}")
            for assertion in case.get("metadata_assertions", []):
                paper_id = assertion.get("paper_id")
                paper = papers.get(paper_id)
                if paper is None:
                    errors.append(f"{case_id}: metadata assertion has unknown paper_id {paper_id}")
                    continue
                expected_authors = json.loads(paper["authors"]) if paper["authors"] else []
                expected = {
                    "title": paper["title"],
                    "authors": expected_authors,
                    "year": paper["year"],
                    "venue": paper["venue"],
                }
                for field, expected_value in expected.items():
                    if assertion.get(field) != expected_value:
                        errors.append(
                            f"{case_id}: metadata {field} mismatch for {paper_id}: "
                            f"dataset={assertion.get(field)!r} db={expected_value!r}"
                        )
            absence = case.get("corpus_absence_check")
            if isinstance(absence, dict):
                terms = [str(term).casefold() for term in absence.get("terms", [])]
                matched_chunk_ids: set[str] = set()
                for term in terms:
                    matched_chunk_ids.update(
                        row[0]
                        for row in connection.execute(
                            "SELECT chunk_id FROM chunk WHERE instr(lower(text), ?) > 0", (term,)
                        )
                    )
                if len(matched_chunk_ids) != absence.get("matching_chunk_count"):
                    errors.append(
                        f"{case_id}: corpus absence count mismatch: "
                        f"dataset={absence.get('matching_chunk_count')} db={len(matched_chunk_ids)}"
                    )
    finally:
        connection.close()
    return errors


def validate_distribution(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    category_counts = Counter(case.get("category") for case in cases)
    split_counts = Counter(case.get("split") for case in cases)
    if len(cases) != 50:
        errors.append(f"expected 50 cases, found {len(cases)}")
    if category_counts != Counter(CATEGORY_TARGETS):
        errors.append(f"category distribution mismatch: {dict(sorted(category_counts.items()))}")
    if split_counts != Counter({"dev": 30, "test": 20}):
        errors.append(f"split distribution mismatch: {dict(sorted(split_counts.items()))}")
    return errors


def main() -> int:
    args = parse_args()
    if not args.dataset.is_file():
        print(f"ERROR: dataset not found: {args.dataset}", file=sys.stderr)
        return 2
    if not args.database.is_file():
        print(f"ERROR: database not found: {args.database}", file=sys.stderr)
        return 2
    cases, errors = load_cases(args.dataset)
    errors.extend(validate_structure(cases))
    errors.extend(validate_database(cases, args.database))
    errors.extend(validate_distribution(cases))
    clean_cases = [{key: value for key, value in case.items() if key != "_line_number"} for case in cases]
    category_counts = Counter(case.get("category") for case in clean_cases)
    split_counts = Counter(case.get("split") for case in clean_cases)
    uncertainty_counts = Counter(case.get("annotation_uncertainty") for case in clean_cases)
    print(f"dataset={args.dataset}")
    print(f"database={args.database}")
    print(f"cases={len(clean_cases)}")
    print(f"categories={json.dumps(dict(sorted(category_counts.items())), sort_keys=True)}")
    print(f"splits={json.dumps(dict(sorted(split_counts.items())), sort_keys=True)}")
    print(f"uncertainty={json.dumps(dict(sorted(uncertainty_counts.items())), sort_keys=True)}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("status=valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
