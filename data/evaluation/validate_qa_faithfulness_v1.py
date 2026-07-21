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
EXPECTED_REQUESTED_PROVIDER = "offline_extractive"
EXPECTED_GENERATED_PROVIDER_MODEL = ("offline_extractive", "sentence-overlap-v1")
EXPECTED_NOT_INVOKED_PROVIDER_MODEL = ("not_invoked", "not_invoked")
EXPECTED_RETRIEVAL_MODE = "hybrid"
EXPECTED_RETRIEVAL_SCOPE = "technical"
EXPECTED_TOP_K = 5


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
            _validate_answer_contract(row, answer, raw)
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
    assert metrics["answer_provider"] == metrics["configured_answer_provider"] == EXPECTED_REQUESTED_PROVIDER
    assert metrics["answer_model"] == metrics["configured_answer_model"] == EXPECTED_GENERATED_PROVIDER_MODEL[1]
    assert metrics["observed_answer_providers"] == dict(
        sorted(Counter(str(row["provider"]) for row in final_rows).items())
    )
    assert metrics["observed_answer_models"] == dict(
        sorted(Counter(str(row["model"]) for row in final_rows).items())
    )
    assert metrics["provider_not_invoked_case_ids"] == sorted(
        str(row["qa_case_id"])
        for row in final_rows
        if (row["provider"], row["model"]) == EXPECTED_NOT_INVOKED_PROVIDER_MODEL
    )
    unanswerable_rows = [row for row in final_rows if row["answerability"] == "unanswerable"]
    expected_unanswerable_abstention_rate = round(
        sum(bool(row["did_abstain"]) for row in unanswerable_rows) / len(unanswerable_rows),
        6,
    )
    assert metrics["metrics"]["unanswerable_abstention_rate"] == expected_unanswerable_abstention_rate

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "executed_and_validated"
    for relative_path, expected_hash in manifest["files"].items():
        path = ROOT / relative_path
        assert path.exists() and sha256_path(path) == expected_hash, relative_path
    ollama = json.loads(OLLAMA.read_text(encoding="utf-8"))
    if ollama["status"] == "unavailable":
        assert ollama["comparison_status"] == "not_run"
        assert not ollama["installed_models"]


def _validate_answer_contract(row: dict, answer: dict, raw: dict) -> None:
    """Validate requested configuration and the conditional generation identity.

    A pre-generation answerability rejection is a legitimate abstention. In
    that branch the requested offline provider is deliberately not called, so
    the effective provider/model pair is ``not_invoked``. Any non-abstaining
    answer, and any abstention produced after generation, must retain the
    pinned offline-extractive provider/model identity.
    """

    case_id = str(row["qa_case_id"])
    raw_request = raw["request"]
    raw_response = raw["response"]

    assert raw["qa_case_id"] == answer["qa_case_id"] == case_id, f"{case_id}: record identity mismatch"
    assert row["question"] == answer["question"] == raw_request["question"] == raw_response["question"], (
        f"{case_id}: question mismatch"
    )
    assert row["answer"] == answer["answer"] == raw_response["answer"], f"{case_id}: answer text mismatch"
    expected_answer_sha256 = hashlib.sha256(row["answer"].encode("utf-8")).hexdigest()
    assert row["answer_sha256"] == answer["answer_sha256"] == expected_answer_sha256, (
        f"{case_id}: answer hash mismatch"
    )

    provider_model = (str(row["provider"]), str(row["model"]))
    assert provider_model == (answer["provider"], answer["model"]), f"{case_id}: public provider/model mismatch"
    assert provider_model == (raw_response["provider"], raw_response["model"]), (
        f"{case_id}: raw provider/model mismatch"
    )
    assert provider_model in {EXPECTED_GENERATED_PROVIDER_MODEL, EXPECTED_NOT_INVOKED_PROVIDER_MODEL}, (
        f"{case_id}: unexpected provider/model pair {provider_model}"
    )

    did_abstain = bool(row["did_abstain"])
    assert did_abstain == bool(answer["did_abstain"]), f"{case_id}: answer abstention mismatch"
    assert did_abstain == bool(answer["segmentation"]["did_abstain"]), f"{case_id}: segmentation mismatch"
    assert did_abstain == bool(row["creation_review"]["did_abstain"]), f"{case_id}: creation review mismatch"
    assert did_abstain == bool(row["verification_review"]["did_abstain"]), (
        f"{case_id}: verification review mismatch"
    )

    assert raw_request["provider"] == answer["requested_provider"] == EXPECTED_REQUESTED_PROVIDER, (
        f"{case_id}: requested provider mismatch"
    )
    assert raw_request["model"] is None and answer["requested_model"] is None, f"{case_id}: requested model mismatch"
    assert raw_request["mode"] == answer["retrieval_mode"] == row["retrieval_mode"] == raw_response["retrieval_mode"] == EXPECTED_RETRIEVAL_MODE, (
        f"{case_id}: retrieval mode mismatch"
    )
    assert raw_request["top_k"] == answer["top_k"] == row["top_k"] == raw_response["top_k"] == EXPECTED_TOP_K, (
        f"{case_id}: top-k mismatch"
    )
    assert raw_request["retrieval_scope"] == EXPECTED_RETRIEVAL_SCOPE, f"{case_id}: request scope mismatch"
    assert answer["retrieval_metadata"]["retrieval_scope"] == EXPECTED_RETRIEVAL_SCOPE, (
        f"{case_id}: public response scope mismatch"
    )
    assert raw_response["retrieval_metadata"]["retrieval_scope"] == EXPECTED_RETRIEVAL_SCOPE, (
        f"{case_id}: raw response scope mismatch"
    )

    raw_citation_ids = [citation["chunk_id"] for citation in raw_response["citations"]]
    assert row["returned_citation_ids"] == answer["returned_citation_ids"] == raw_citation_ids, (
        f"{case_id}: returned citation mismatch"
    )
    resolution = raw_response["generation_metadata"]["provider_resolution"]
    assert resolution["requested_provider"] == EXPECTED_REQUESTED_PROVIDER, f"{case_id}: resolution request mismatch"
    assert resolution["requested_model"] is None, f"{case_id}: resolution model request mismatch"
    assert resolution["configured_provider"] == EXPECTED_REQUESTED_PROVIDER, (
        f"{case_id}: configured provider mismatch"
    )
    assert resolution["configured_model"] == EXPECTED_GENERATED_PROVIDER_MODEL[1], (
        f"{case_id}: configured model mismatch"
    )
    assert resolution["fallback_used"] is False, f"{case_id}: unexpected provider fallback"

    if provider_model == EXPECTED_NOT_INVOKED_PROVIDER_MODEL:
        assert did_abstain, f"{case_id}: a non-invocation must be an abstention"
        assert raw_response["answerability"]["answerable"] is False, (
            f"{case_id}: non-invocation requires a failed answerability gate"
        )
        assert raw_response["grounding_status"] == "unsupported", f"{case_id}: abstention grounding mismatch"
        assert not raw_citation_ids and not row["returned_citation_ids"], (
            f"{case_id}: a pre-generation abstention cannot cite generated evidence"
        )
        assert not answer["segmentation"]["claims"] and not row["adjudicated_claims"], (
            f"{case_id}: a pre-generation abstention cannot contain adjudicated claims"
        )
        assert resolution["effective_provider"] == "not_invoked" and resolution["effective_model"] is None, (
            f"{case_id}: non-invocation resolution mismatch"
        )
    else:
        assert raw_response["answerability"]["answerable"] is True, (
            f"{case_id}: generation requires a passed answerability gate"
        )
        assert resolution["effective_provider"] == provider_model[0], f"{case_id}: effective provider mismatch"
        assert resolution["effective_model"] == provider_model[1], f"{case_id}: effective model mismatch"


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
