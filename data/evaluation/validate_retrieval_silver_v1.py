#!/usr/bin/env python3
"""Validate the independently verified TTLAB silver retrieval set."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from validate_retrieval_silver_create_v1 import (
    CATEGORY_TARGETS,
    EXCLUDED_MISMATCHED_PAPERS,
    ROOT,
    load_cases,
    validate_database,
)


DEFAULT_DATASET = ROOT / "data/evaluation/retrieval_silver_v1.jsonl"
DEFAULT_SOURCE = ROOT / "data/evaluation/retrieval_silver_create_v1.jsonl"
DEFAULT_DATABASE = ROOT / "data/papers.db"
SHUFFLE_SEED = 20260712
REVISED_SOURCE_CASES = {
    "ret-create-006",
    "ret-create-009",
    "ret-create-031",
    "ret-create-037",
    "ret-create-038",
    "ret-create-041",
}
CORE_LABEL_FIELDS = {
    "question",
    "category",
    "answerability",
    "relevant_paper_ids",
    "supporting_evidence",
    "distractor_paper_ids",
    "rationale",
    "split",
    "annotation_uncertainty",
    "second_pass_note",
    "metadata_assertions",
    "corpus_absence_check",
}
REQUIRED_KEYS = {
    "case_id",
    "source_case_id",
    "question",
    "category",
    "answerability",
    "relevant_paper_ids",
    "supporting_evidence",
    "distractor_paper_ids",
    "rationale",
    "split",
    "label_quality",
    "timestamp",
    "annotation_uncertainty",
    "second_pass_note",
    "decision",
    "verification_rationale",
    "disagreement",
    "adjudication",
    "relevance_judgments",
    "creation_annotation",
    "verifier_id",
    "reviewer_type",
    "pass",
    "shuffled_position",
    "shuffle_seed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser.parse_args()


def case_core(case: dict[str, Any]) -> dict[str, Any]:
    return {field: case.get(field) for field in CORE_LABEL_FIELDS if field in case}


def validate_structure(
    cases: list[dict[str, Any]], source_cases: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    source_by_id = {case["case_id"]: case for case in source_cases}
    expected_order = list(source_by_id)
    random.Random(SHUFFLE_SEED).shuffle(expected_order)
    seen_case_ids: set[str] = set()
    seen_source_ids: set[str] = set()
    for expected_position, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id", f"line-{case.get('_line_number')}"))
        missing = sorted(REQUIRED_KEYS - case.keys())
        if missing:
            errors.append(f"{case_id}: missing keys: {', '.join(missing)}")
        if case_id in seen_case_ids:
            errors.append(f"{case_id}: duplicate final case ID")
        seen_case_ids.add(case_id)
        source_id = case.get("source_case_id")
        if source_id in seen_source_ids:
            errors.append(f"{case_id}: duplicate source_case_id {source_id}")
        seen_source_ids.add(source_id)
        if source_id not in source_by_id:
            errors.append(f"{case_id}: unknown source_case_id {source_id}")
            continue
        if case_id != str(source_id).replace("ret-create-", "ret-silver-"):
            errors.append(f"{case_id}: final/source ID mapping is inconsistent")
        if case.get("shuffled_position") != expected_position:
            errors.append(f"{case_id}: shuffled_position must equal file position {expected_position}")
        if expected_order[expected_position - 1] != source_id:
            errors.append(
                f"{case_id}: fixed-seed order mismatch: expected {expected_order[expected_position - 1]}, got {source_id}"
            )
        if case.get("shuffle_seed") != SHUFFLE_SEED:
            errors.append(f"{case_id}: wrong shuffle seed")
        if case.get("verifier_id") != "codex-ai-review" or case.get("reviewer_type") != "ai":
            errors.append(f"{case_id}: verifier identity/type must be codex-ai-review/ai")
        if case.get("pass") != "verify" or case.get("label_quality") != "silver":
            errors.append(f"{case_id}: final pass/quality must be verify/silver")
        try:
            datetime.fromisoformat(str(case.get("timestamp")).replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{case_id}: invalid verification timestamp")
        source = source_by_id[source_id]
        creation = case.get("creation_annotation")
        expected_creation = {
            "reviewer_id": source.get("reviewer_id"),
            "reviewer_type": source.get("reviewer_type"),
            "pass": source.get("pass"),
            "timestamp": source.get("timestamp"),
        }
        if creation != expected_creation:
            errors.append(f"{case_id}: creation_annotation does not reproduce create-pass provenance")
        relevant = case.get("relevant_paper_ids", [])
        distractors = case.get("distractor_paper_ids", [])
        evidence = case.get("supporting_evidence", [])
        if len(relevant) != len(set(relevant)) or len(distractors) != len(set(distractors)):
            errors.append(f"{case_id}: paper ID lists must be unique")
        if set(relevant) & set(distractors):
            errors.append(f"{case_id}: relevant and distractor sets overlap")
        excluded = (set(relevant) | set(distractors)) & EXCLUDED_MISMATCHED_PAPERS
        if excluded:
            errors.append(f"{case_id}: references title/PDF mismatch papers: {sorted(excluded)}")
        evidenced = {item.get("paper_id") for item in evidence if isinstance(item, dict)}
        if case.get("answerability") == "answerable":
            if not relevant or set(relevant) - evidenced:
                errors.append(f"{case_id}: every answerable relevant paper needs source evidence")
        elif case.get("answerability") == "unanswerable":
            if relevant or evidence or not case.get("corpus_absence_check"):
                errors.append(f"{case_id}: invalid unanswerable evidence state")
        else:
            errors.append(f"{case_id}: invalid answerability")
        expected_judgments = [
            {"paper_id": paper_id, "grade": 2, "label": "directly_relevant"}
            for paper_id in relevant
        ] + [
            {"paper_id": paper_id, "grade": 0, "label": "hard_negative"}
            for paper_id in distractors
        ]
        if case.get("relevance_judgments") != expected_judgments:
            errors.append(f"{case_id}: relevance_judgments do not match relevant/distractor sets")
        source_core = case_core(source)
        final_core = case_core(case)
        changed_fields = sorted(
            field for field in CORE_LABEL_FIELDS if source_core.get(field) != final_core.get(field)
        )
        decision = case.get("decision")
        if decision == "agree":
            if changed_fields:
                errors.append(f"{case_id}: agree case changed fields: {changed_fields}")
            if case.get("disagreement") is not None:
                errors.append(f"{case_id}: agree case must have null disagreement")
            if case.get("adjudication", {}).get("status") != "not_needed":
                errors.append(f"{case_id}: agree case must use not_needed adjudication")
        elif decision == "revise":
            disagreement = case.get("disagreement")
            if not isinstance(disagreement, dict):
                errors.append(f"{case_id}: revised case needs disagreement details")
            elif sorted(disagreement.get("fields", [])) != changed_fields:
                errors.append(
                    f"{case_id}: disagreement fields {disagreement.get('fields')} do not match actual changes {changed_fields}"
                )
            if case.get("adjudication", {}).get("status") != "resolved_by_ai_verifier":
                errors.append(f"{case_id}: revised case must record resolved AI adjudication")
        else:
            errors.append(f"{case_id}: decision must be agree or revise")
    if seen_source_ids != set(source_by_id):
        errors.append("final dataset does not contain every create-pass source case exactly once")
    actual_revised = {case.get("source_case_id") for case in cases if case.get("decision") == "revise"}
    if actual_revised != REVISED_SOURCE_CASES:
        errors.append(f"unexpected revised-case set: {sorted(actual_revised)}")
    return errors


def validate_distribution(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    categories = Counter(case.get("category") for case in cases)
    splits = Counter(case.get("split") for case in cases)
    decisions = Counter(case.get("decision") for case in cases)
    if len(cases) != 50:
        errors.append(f"expected 50 cases, found {len(cases)}")
    if categories != Counter(CATEGORY_TARGETS):
        errors.append(f"category distribution mismatch: {dict(categories)}")
    if splits != Counter({"dev": 30, "test": 20}):
        errors.append(f"split distribution mismatch: {dict(splits)}")
    if decisions != Counter({"agree": 44, "revise": 6}):
        errors.append(f"decision distribution mismatch: {dict(decisions)}")
    return errors


def annotation_consistency(
    cases: list[dict[str, Any]], source_cases: list[dict[str, Any]]
) -> dict[str, float | int]:
    source_by_id = {case["case_id"]: case for case in source_cases}
    pairs: list[tuple[int, int]] = []
    for case in cases:
        source = source_by_id[case["source_case_id"]]
        candidates = (
            set(source.get("relevant_paper_ids", []))
            | set(source.get("distractor_paper_ids", []))
            | set(case.get("relevant_paper_ids", []))
            | set(case.get("distractor_paper_ids", []))
        )
        source_relevant = set(source.get("relevant_paper_ids", []))
        final_relevant = set(case.get("relevant_paper_ids", []))
        pairs.extend((int(paper_id in source_relevant), int(paper_id in final_relevant)) for paper_id in candidates)
    total = len(pairs)
    agreements = sum(1 for first, second in pairs if first == second)
    first_positive = sum(first for first, _ in pairs)
    second_positive = sum(second for _, second in pairs)
    observed = agreements / total
    expected = (
        (first_positive / total) * (second_positive / total)
        + ((total - first_positive) / total) * ((total - second_positive) / total)
    )
    kappa = (observed - expected) / (1 - expected) if not math.isclose(expected, 1.0) else float("nan")
    return {
        "candidate_judgments": total,
        "agreements": agreements,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "cohen_style_kappa": kappa,
    }


def main() -> int:
    args = parse_args()
    for path in (args.dataset, args.source, args.database):
        if not path.is_file():
            print(f"ERROR: required input missing: {path}", file=sys.stderr)
            return 2
    cases, errors = load_cases(args.dataset)
    source_cases, source_errors = load_cases(args.source)
    errors.extend(f"source: {error}" for error in source_errors)
    errors.extend(validate_structure(cases, source_cases))
    errors.extend(validate_database(cases, args.database))
    errors.extend(validate_distribution(cases))
    stats = annotation_consistency(cases, source_cases)
    print(f"dataset={args.dataset}")
    print(f"source={args.source}")
    print(f"database={args.database}")
    print(f"cases={len(cases)}")
    print(f"categories={json.dumps(dict(sorted(Counter(case.get('category') for case in cases).items())))}")
    print(f"splits={json.dumps(dict(sorted(Counter(case.get('split') for case in cases).items())))}")
    print(f"decisions={json.dumps(dict(sorted(Counter(case.get('decision') for case in cases).items())))}")
    print(f"case_exact_agreement={44 / 50:.6f}")
    print(f"candidate_relevance_judgments={stats['candidate_judgments']}")
    print(f"annotation_consistency_observed={stats['observed_agreement']:.6f}")
    print(f"annotation_consistency_expected={stats['expected_agreement']:.6f}")
    print(f"annotation_consistency_cohen_style_kappa={stats['cohen_style_kappa']:.6f}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("status=valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
