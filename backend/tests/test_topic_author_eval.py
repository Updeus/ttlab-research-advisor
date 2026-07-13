from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.topic_author_eval import UNKNOWN, calculate_metrics, wilson


ROOT = Path(__file__).resolve().parents[2]


def test_multilabel_metrics_include_other_unknown_and_per_label_intervals() -> None:
    cases = [
        {"case_id": "one", "final_labels": ["ai", "rag"]},
        {"case_id": "two", "final_labels": []},
    ]
    predictions = {"one": {"ai", "rag"}, "two": {UNKNOWN}}
    result = calculate_metrics(cases, predictions, labels=["ai", "rag", UNKNOWN])

    assert result["micro"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert result["macro"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert result["macro_supported_label_count"] == 3
    assert result["exact_match"] == 1.0
    assert result["coverage"] == 0.5
    assert result["per_label"][UNKNOWN]["recall_wilson_95_ci"][0] < 1.0


def test_metrics_penalize_false_positive_and_false_negative() -> None:
    cases = [{"case_id": "one", "final_labels": ["ai"]}]
    result = calculate_metrics(cases, {"one": {"rag"}}, labels=["ai", "rag", UNKNOWN])

    assert result["micro"]["precision"] == 0.0
    assert result["micro"]["recall"] == 0.0
    assert result["per_label"]["rag"]["fp"] == 1
    assert result["per_label"]["ai"]["fn"] == 1


def test_wilson_interval_is_bounded_and_empty_denominator_is_explicit() -> None:
    lower, upper = wilson(3, 5)
    assert 0.0 <= lower < 0.6 < upper <= 1.0
    assert wilson(0, 0) == [None, None]


def test_topic_silver_is_stratified_two_pass_ai_review_with_bounded_snippets() -> None:
    path = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    assert len(records) == 60
    assert {record["split"] for record in records} == {"dev", "test"}
    assert {record["stratum"] for record in records} == {"single_label", "multi_label", "other_unknown"}
    assert all(len(record["review_passes"]) == 2 for record in records)
    assert all(item["reviewer_type"] == "ai" for record in records for item in record["review_passes"])
    assert all(
        len(evidence["text"]) <= 500
        for record in records
        for evidence in record["evidence"]
        if evidence["evidence_type"] == "source_chunk"
    )
    assert any(record["final_other_unknown"] for record in records)
    assert any(len(record["final_labels"]) > 1 for record in records)


@pytest.mark.parametrize("case_id", ["topic-silver-001", "topic-silver-060"])
def test_topic_silver_retains_source_hashes_for_boundary_cases(case_id: str) -> None:
    path = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
    record = next(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if case_id in line)
    chunks = [item for item in record["evidence"] if item["evidence_type"] == "source_chunk"]

    assert chunks
    assert all(len(item["source_hash"]) == 64 for item in chunks)
