#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import jsonschema
from sqlmodel import Session

from app.db import engine
from app.evaluation.qa_faithfulness_eval import calculate_faithfulness_metrics, load_jsonl, sha256_path
from app.models import Chunk, Paper


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data/evaluation/qa_faithfulness_cases_v1.jsonl"
CASE_SCHEMA = ROOT / "data/evaluation/qa_faithfulness_cases_v1.schema.json"
ANSWERS = ROOT / "artifacts/phase3/qa/offline_extractive_hybrid_heuristic_answers_v1.jsonl"
RAW = ROOT / "artifacts/phase3/private/qa/offline_extractive_hybrid_heuristic_raw_inputs_outputs_v1.jsonl"
CREATE = ROOT / "data/evaluation/qa_faithfulness_review_create_v1.jsonl"
VERIFY = ROOT / "data/evaluation/qa_faithfulness_review_verify_v1.jsonl"
FINAL = ROOT / "data/evaluation/qa_faithfulness_results_v1.jsonl"
RESULT_SCHEMA = ROOT / "data/evaluation/qa_faithfulness_results_v1.schema.json"
METRICS = ROOT / "artifacts/phase3/qa/qa_faithfulness_metrics_v1.json"
MANIFEST = ROOT / "artifacts/phase3/qa/qa_faithfulness_manifest_v1.json"
OLLAMA = ROOT / "artifacts/phase3/qa/ollama_availability_v1.json"


def validate() -> None:
    case_rows = load_jsonl(CASES)
    answer_rows = load_jsonl(ANSWERS)
    raw_rows = load_jsonl(RAW)
    create_rows = load_jsonl(CREATE)
    verify_rows = load_jsonl(VERIFY)
    final_rows = load_jsonl(FINAL)
    _validate_schema(case_rows, CASE_SCHEMA)
    _validate_schema(final_rows, RESULT_SCHEMA)

    expected_ids = {f"qa-silver-{index:03d}" for index in range(1, 51)}
    collections = (case_rows, answer_rows, raw_rows, create_rows, verify_rows, final_rows)
    for rows in collections:
        assert len(rows) == 50
        assert {str(row["qa_case_id"]) for row in rows} == expected_ids
    assert Counter(row["answerability"] for row in case_rows) == Counter({"answerable": 46, "unanswerable": 4})
    assert len({row["category"] for row in case_rows}) == 11
    assert sum(len(row["answer_points"]) for row in case_rows) == 81
    assert sum(len(row["supporting_sources"]) for row in case_rows) == 76

    create_by_id = {row["qa_case_id"]: row for row in create_rows}
    verify_by_id = {row["qa_case_id"]: row for row in verify_rows}
    answer_by_id = {row["qa_case_id"]: row for row in answer_rows}
    raw_by_id = {row["qa_case_id"]: row for row in raw_rows}
    assert all(row["review_pass"] == "create" and row["reviewer_type"] == "ai" for row in create_rows)
    assert all(row["review_pass"] == "verify_shuffled" and row["reviewer_type"] == "ai" for row in verify_rows)
    assert sorted(int(row["shuffled_position"]) for row in verify_rows) == list(range(1, 51))
    assert {row["shuffle_seed"] for row in verify_rows} == {20260713}

    with Session(engine) as session:
        for case in case_rows:
            for source in case["supporting_sources"]:
                chunk = session.get(Chunk, source["chunk_id"])
                paper = session.get(Paper, source["paper_id"])
                assert chunk is not None and paper is not None
                assert chunk.paper_id == source["paper_id"]
                assert chunk.source_hash == source["source_hash"]
                assert chunk.page_start == source["page_start"] and chunk.page_end == source["page_end"]

        for row in final_rows:
            case_id = row["qa_case_id"]
            answer = answer_by_id[case_id]
            raw = raw_by_id[case_id]
            assert hashlib.sha256(row["answer"].encode("utf-8")).hexdigest() == row["answer_sha256"]
            assert row["answer_sha256"] == answer["answer_sha256"]
            assert row["provider"] == "offline_extractive" and row["model"] == "sentence-overlap-v1"
            assert row["retrieval_mode"] == "hybrid" and row["top_k"] == 5
            assert row["creation_review"]["raw_prompt_sha256"] == create_by_id[case_id]["raw_prompt_sha256"]
            assert row["verification_review"]["raw_prompt_sha256"] == verify_by_id[case_id]["raw_prompt_sha256"]
            source_records = {source["chunk_id"]: source for source in raw["source_records"]}
            for claim in row["adjudicated_claims"]:
                assert claim["citation_judgments"]
                for citation in claim["citation_judgments"]:
                    if citation["source_id"] is None:
                        assert citation["citation_label"] == "missing"
                        continue
                    assert citation["source_id"] in source_records
                    source = source_records[citation["source_id"]]
                    assert source["page_start"] == citation["page_start"]
                    assert source["page_end"] == citation["page_end"]
                    assert source["pages"], f"No extracted page text for {citation['source_id']}"
                    chunk = session.get(Chunk, citation["source_id"])
                    assert chunk is not None and chunk.source_hash == source["chunk_source_hash"]

    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    recomputed = calculate_faithfulness_metrics(final_rows)
    for key in ("case_count", "metric_definitions", "counts", "metrics", "confidence_intervals", "category_results", "error_taxonomy", "review_consistency", "limitations"):
        assert metrics[key] == recomputed[key], f"Metric mismatch: {key}"
    assert metrics["reviewer_type"] == "ai"
    assert metrics["metrics"]["unanswerable_abstention_rate"] == 0.0

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "executed_and_validated"
    for relative_path, expected_hash in manifest["files"].items():
        path = ROOT / relative_path
        assert path.exists() and sha256_path(path) == expected_hash, relative_path
    ollama = json.loads(OLLAMA.read_text(encoding="utf-8"))
    if ollama["status"] == "unavailable":
        assert ollama["comparison_status"] == "not_run"
        assert not ollama["installed_models"]


def _validate_schema(rows: list[dict], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = []
    for index, row in enumerate(rows, start=1):
        errors.extend(f"row {index}: {error.message}" for error in validator.iter_errors(row))
    if errors:
        raise AssertionError("\n".join(errors[:20]))


if __name__ == "__main__":
    validate()
    print("status=valid cases=50 answer_points=81 reviewer_type=ai passes=2")
