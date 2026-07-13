import json
import math
from pathlib import Path

import pytest

from app.evaluation.retrieval_eval import (
    bootstrap_metric_intervals,
    calculate_metrics,
    capture_ranking_rows,
    evaluate_ranked_query,
    load_questions,
    normalized_discounted_cumulative_gain,
)
from app.evaluation.compare_retrieval_runs import compare_retrieval_results
from app.evaluation.statistics import (
    bootstrap_mean_interval,
    compare_paired_runs,
    holm_bonferroni,
    paired_bootstrap_mean_difference,
    paired_permutation_test,
    percentile,
)


def answerable_query(case_id: str, relevant: list[str], judgments: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "case_id": case_id,
        "question": f"Question text for {case_id}",
        "answerability": "answerable",
        "relevant_paper_ids": relevant,
        "relevance_judgments": judgments or [],
    }


def unanswerable_query(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "question": f"Out of corpus question for {case_id}",
        "answerability": "unanswerable",
        "relevant_paper_ids": [],
        "relevance_judgments": [],
    }


def test_set_recall_hit_and_precision_have_distinct_hand_computed_definitions() -> None:
    first = evaluate_ranked_query(answerable_query("q1", ["a", "b"]), ["a", "x", "b"])
    second = evaluate_ranked_query(answerable_query("q2", ["c", "d"]), ["x", "c"])
    metrics = calculate_metrics([first, second])

    # q1 finds 2/2 and q2 finds 1/2, while both have at least one hit.
    assert metrics["set_recall_at_3"] == 0.75
    assert metrics["hit_at_3"] == 1.0
    # Standard P@3 has a fixed denominator: mean((2/3), (1/3)) = 1/2.
    assert metrics["precision_at_3"] == 0.5
    assert metrics["mrr"] == 0.75  # mean(1, 1/2)


def test_recall_uses_all_relevant_papers_not_a_binary_hit() -> None:
    row = evaluate_ranked_query(answerable_query("q1", ["a", "b", "c", "d"]), ["a", "x", "y"])

    assert row["metrics"]["set_recall_at_3"] == 0.25
    assert row["metrics"]["hit_at_3"] is True
    assert row["metrics"]["precision_at_3"] == pytest.approx(1 / 3)


def test_ndcg_at_10_uses_explicit_graded_relevance() -> None:
    grades = {"a": 2, "b": 1}
    actual = normalized_discounted_cumulative_gain(["a", "x", "b"], grades, cutoff=10)
    expected = (3.0 + 1.0 / math.log2(4.0)) / (3.0 + 1.0 / math.log2(3.0))

    assert actual == pytest.approx(expected)
    assert actual == pytest.approx(0.9639404333)
    assert normalized_discounted_cumulative_gain(["x"], {"x": 0}, cutoff=10) is None


def test_binary_legacy_labels_do_not_masquerade_as_graded_ndcg() -> None:
    row = evaluate_ranked_query(answerable_query("q1", ["a"]), ["a"])

    assert row["metrics"]["ndcg_at_10"] is None


def test_unanswerable_abstention_and_false_positive_rates_are_separate() -> None:
    false_positive = evaluate_ranked_query(unanswerable_query("u1"), ["irrelevant"])
    abstained = evaluate_ranked_query(unanswerable_query("u2"), [])
    metrics = calculate_metrics([false_positive, abstained])

    assert metrics["unanswerable_abstention_rate"] == 0.5
    assert metrics["unanswerable_false_positive_rate"] == 0.5
    assert metrics["unanswerable_false_positive_at_3"] == 0.5
    assert metrics["set_recall_at_3"] is None


def test_load_questions_accepts_explicit_unanswerable_and_rejects_ambiguous_empty_legacy_set(tmp_path: Path) -> None:
    valid = tmp_path / "valid.jsonl"
    valid.write_text(json.dumps(unanswerable_query("u1")) + "\n", encoding="utf-8")
    loaded = load_questions(valid)
    assert loaded[0]["answerability"] == "unanswerable"

    ambiguous = tmp_path / "ambiguous.jsonl"
    ambiguous.write_text(json.dumps({"question": "Is this absent?", "gold_paper_ids": []}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty legacy relevance set"):
        load_questions(ambiguous)


def test_load_questions_checks_positive_grades_against_relevant_set(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(
            {
                **answerable_query("q1", ["a"]),
                "relevance_judgments": [{"paper_id": "b", "grade": 2}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inconsistent"):
        load_questions(path)


def test_capture_ranking_rows_deduplicates_papers_at_their_first_chunk_rank() -> None:
    rows = capture_ranking_rows(
        [
            {"paper_id": "a", "chunk_id": "a-1", "score": 0.9},
            {"paper_id": "a", "chunk_id": "a-2", "score": 0.8},
            {"paper_id": "b", "chunk_id": "b-1", "score": 0.7},
        ]
    )

    assert [row["paper_id"] for row in rows] == ["a", "b"]
    assert rows[0]["raw_chunk_rank"] == 1
    assert rows[1]["rank"] == 2
    assert rows[1]["raw_chunk_rank"] == 3


def test_percentile_interpolation_and_bootstrap_are_fixed_seed_reproducible() -> None:
    assert percentile([0.0, 10.0], 0.25) == 2.5
    first = bootstrap_mean_interval([0.0, 1.0], repetitions=50, seed=7)
    second = bootstrap_mean_interval([0.0, 1.0], repetitions=50, seed=7)

    assert first == second
    assert first["estimate"] == 0.5
    assert first["sample_size"] == 2
    assert len(first["replicate_means"]) == 50


def test_metric_bootstrap_resamples_queries_and_retains_raw_replicate_means() -> None:
    rows = [
        evaluate_ranked_query(answerable_query("q1", ["a", "b"]), ["a"]),
        evaluate_ranked_query(answerable_query("q2", ["c", "d"]), ["c", "d"]),
    ]
    output = bootstrap_metric_intervals(rows, repetitions=25, seed=11)
    recall = output["metrics"]["set_recall_at_3"]

    assert recall["estimate"] == 0.75
    assert recall["unit"] == "query"
    assert recall["seed"] == 11
    assert len(recall["replicate_means"]) == 25
    assert output["label_uncertainty_included"] is False


def test_paired_bootstrap_uses_within_query_differences() -> None:
    output = paired_bootstrap_mean_difference([0.0, 0.5], [0.5, 1.0], repetitions=20, seed=3)

    assert output["estimate"] == 0.5
    assert output["ci_lower"] == 0.5
    assert output["ci_upper"] == 0.5
    assert output["contrast"] == "candidate_minus_baseline"


def test_exact_paired_randomization_has_hand_computed_p_value() -> None:
    # Four sign assignments for differences [1, 1]; two are as extreme as |mean|=1.
    output = paired_permutation_test([0.0, 0.0], [1.0, 1.0])

    assert output["method"] == "paired_randomization_exact"
    assert output["randomizations"] == 4
    assert output["mean_difference"] == 1.0
    assert output["p_value"] == 0.5


def test_holm_bonferroni_is_step_down_and_monotone() -> None:
    output = holm_bonferroni({"a": 0.01, "b": 0.04, "c": 0.03}, familywise_alpha=0.05)

    assert output["a"]["adjusted_p_value"] == pytest.approx(0.03)
    assert output["a"]["reject_null"] is True
    assert output["c"]["adjusted_p_value"] == pytest.approx(0.06)
    assert output["c"]["reject_null"] is False
    assert output["b"]["adjusted_p_value"] == pytest.approx(0.06)
    assert output["b"]["reject_null"] is False


def test_compare_paired_runs_requires_identical_query_ids() -> None:
    baseline = [{"case_id": "q1", "metrics": {"mrr": 0.0}}]
    candidate = [{"case_id": "q2", "metrics": {"mrr": 1.0}}]

    with pytest.raises(ValueError, match="identical case IDs"):
        compare_paired_runs(baseline, candidate, metric="mrr", repetitions=10)


def test_compare_paired_runs_reports_test_and_confidence_interval() -> None:
    baseline = [
        {"case_id": "q1", "metrics": {"mrr": 0.0}},
        {"case_id": "q2", "metrics": {"mrr": 0.5}},
    ]
    candidate = [
        {"case_id": "q1", "metrics": {"mrr": 0.5}},
        {"case_id": "q2", "metrics": {"mrr": 1.0}},
    ]
    output = compare_paired_runs(baseline, candidate, metric="mrr", repetitions=20, seed=4)

    assert output["paired_query_count"] == 2
    assert output["mean_difference"] == 0.5
    assert output["paired_test"]["p_value"] == 0.5
    assert output["confidence_interval"]["estimate"] == 0.5


def test_compare_paired_runs_maps_aggregate_mrr_name_to_query_reciprocal_rank() -> None:
    baseline = [{"case_id": "q1", "metrics": {"reciprocal_rank": 0.0}}]
    candidate = [{"case_id": "q1", "metrics": {"reciprocal_rank": 1.0}}]

    output = compare_paired_runs(baseline, candidate, metric="mrr", repetitions=10)

    assert output["metric"] == "mrr"
    assert output["mean_difference"] == 1.0


def test_retrieval_result_comparison_enforces_frozen_controls_and_applies_holm() -> None:
    controls = {
        "questions_sha256": "a" * 64,
        "evaluated_case_ids_sha256": "c" * 64,
        "top_k": 10,
        "retrieval_depth": 50,
        "cutoffs": [3, 5, 10],
        "filters": {"paper_id": None},
        "corpus": {"snapshot_hash": "b" * 64},
    }
    baseline = {
        "run_config": {**controls, "mode": "keyword"},
        "questions": [
            {"case_id": "q1", "metrics": {"reciprocal_rank": 0.0, "set_recall_at_3": 0.0}},
            {"case_id": "q2", "metrics": {"reciprocal_rank": 0.5, "set_recall_at_3": 0.5}},
        ],
    }
    candidate = {
        "run_config": {**controls, "mode": "dense"},
        "questions": [
            {"case_id": "q1", "metrics": {"reciprocal_rank": 0.5, "set_recall_at_3": 0.5}},
            {"case_id": "q2", "metrics": {"reciprocal_rank": 1.0, "set_recall_at_3": 1.0}},
        ],
    }
    output = compare_retrieval_results(
        baseline,
        candidate,
        metrics=["mrr", "set_recall_at_3"],
        repetitions=20,
        seed=5,
    )

    assert output["baseline_mode"] == "keyword"
    assert output["candidate_mode"] == "dense"
    assert output["comparisons"]["mrr"]["mean_difference"] == 0.5
    assert "multiplicity_correction" in output["comparisons"]["mrr"]


def test_retrieval_result_comparison_rejects_different_corpus_snapshots() -> None:
    baseline = {
        "run_config": {
            "questions_sha256": "a" * 64,
            "evaluated_case_ids_sha256": "d" * 64,
            "top_k": 10,
            "retrieval_depth": 50,
            "cutoffs": [3, 5, 10],
            "filters": {"paper_id": None},
            "corpus": {"snapshot_hash": "b" * 64},
        },
        "questions": [],
    }
    candidate = {
        "run_config": {
            "questions_sha256": "a" * 64,
            "evaluated_case_ids_sha256": "d" * 64,
            "top_k": 10,
            "retrieval_depth": 50,
            "cutoffs": [3, 5, 10],
            "filters": {"paper_id": None},
            "corpus": {"snapshot_hash": "c" * 64},
        },
        "questions": [],
    }

    with pytest.raises(ValueError, match="controls differ"):
        compare_retrieval_results(baseline, candidate, metrics=["mrr"], repetitions=10)


def test_result_schema_declares_all_required_metric_families() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    schema_path = repository_root / "data/evaluation/retrieval_eval_results.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = set(schema["$defs"]["aggregateMetrics"]["required"])

    assert {"set_recall_at_3", "set_recall_at_5", "set_recall_at_10"} <= required
    assert {"hit_at_3", "hit_at_5", "hit_at_10"} <= required
    assert {"precision_at_3", "precision_at_5", "precision_at_10"} <= required
    assert {"mrr", "ndcg_at_10", "unanswerable_abstention_rate", "unanswerable_false_positive_rate"} <= required
