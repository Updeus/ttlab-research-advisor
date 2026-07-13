#!/usr/bin/env python3
"""Fail closed when the Phase 4 topic/author silver evidence drifts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sqlmodel import Session

from app.db import engine
from app.models import Chunk, Paper

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
MANIFEST = ROOT / "data/evaluation/topic_author_silver_v1.manifest.json"
SCHEMA = ROOT / "data/evaluation/topic_author_silver_v1.schema.json"
EXCLUDED_IDS = {
    "pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f",
    "vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(dataset: Path = DATASET) -> dict[str, Any]:
    raw = dataset.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    records = load_jsonl(dataset)
    errors: list[str] = []
    if sha256_bytes(raw) != manifest["dataset_sha256"]:
        errors.append("dataset SHA-256 does not match manifest")
    validator = Draft202012Validator(schema)
    for index, record in enumerate(records, start=1):
        for error in validator.iter_errors(record):
            errors.append(f"line {index}: schema: {error.message}")
    if len(records) != manifest["case_count"] or len(records) < 40:
        errors.append("case count is below the declared stratified sample")
    if len({record["case_id"] for record in records}) != len(records):
        errors.append("case IDs are not unique")
    if len({record["paper_id"] for record in records}) != len(records):
        errors.append("paper IDs are not unique")
    if {record["split"] for record in records} != {"dev", "test"}:
        errors.append("both dev and test splits are required")
    if {record["stratum"] for record in records} != {"single_label", "multi_label", "other_unknown"}:
        errors.append("single-label, multi-label, and other/unknown strata are required")
    label_support = {
        label: sum(label in record["final_labels"] for record in records)
        for label in schema["properties"]["final_labels"]["items"]["enum"]
    }
    if set(label_support) != set(manifest["label_support"]) or label_support != manifest["label_support"]:
        errors.append("label support does not match the manifest")
    if any(value < 1 for value in label_support.values()):
        errors.append("every controlled label must have at least one source-backed silver case")
    with Session(engine) as session:
        for record in records:
            paper = session.get(Paper, record["paper_id"])
            if paper is None:
                errors.append(f"{record['case_id']}: missing paper")
                continue
            if paper.corpus_eligibility_status != "eligible" or paper.paper_id in EXCLUDED_IDS:
                errors.append(f"{record['case_id']}: paper is not in the eligible frozen corpus")
            if paper.title != record["title"]:
                errors.append(f"{record['case_id']}: title drift")
            if record["final_other_unknown"] != (not record["final_labels"]):
                errors.append(f"{record['case_id']}: other/unknown is inconsistent with final labels")
            if record["stratum"] == "other_unknown" and record["final_labels"]:
                errors.append(f"{record['case_id']}: other/unknown case has a controlled label")
            passes = record["review_passes"]
            if [item["pass_id"] for item in passes] != ["create", "verify"]:
                errors.append(f"{record['case_id']}: required review passes are absent")
            if any(item["reviewer_type"] != "ai" for item in passes):
                errors.append(f"{record['case_id']}: reviewer type must be AI")
            if sorted(passes[1]["labels"]) != sorted(record["final_labels"]):
                errors.append(f"{record['case_id']}: final labels do not match verification pass")
            for evidence in record["evidence"]:
                if evidence["evidence_type"] == "paper_title":
                    if sha256_bytes(evidence["text"].encode("utf-8")) != evidence["sha256"]:
                        errors.append(f"{record['case_id']}: title evidence hash drift")
                    continue
                chunk = session.get(Chunk, evidence["chunk_id"])
                if chunk is None or chunk.paper_id != paper.paper_id:
                    errors.append(f"{record['case_id']}: missing or cross-paper source chunk")
                elif chunk.source_hash != evidence["source_hash"]:
                    errors.append(f"{record['case_id']}: source chunk hash drift")
    if errors:
        raise SystemExit("topic/author silver validation failed:\n- " + "\n- ".join(errors))
    return {
        "status": "PASS",
        "cases": len(records),
        "dataset_sha256": manifest["dataset_sha256"],
        "split_counts": manifest["split_counts"],
        "stratum_counts": manifest["stratum_counts"],
        "pass_exact_agreement": manifest["pass_exact_agreement"],
        "reviewer_type": "ai",
        "human_validation": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset), indent=2))


if __name__ == "__main__":
    main()
