from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.retrieval_eval import capture_ranking_rows
from app.evaluation.retrieval_experiment import (
    error_taxonomy,
    select_tuned_configuration,
    split_questions,
)
from app.indexing.retriever import (
    BASELINE_RETRIEVER_CONFIG,
    DEFAULT_RETRIEVER_CONFIG,
    RetrieverConfig,
    rank_retrieval_components,
)


def result(case_id: str, recall: float | None, *, candidates: list[str] | None = None) -> dict:
    return {
        "questions": [
            {
                "case_id": case_id,
                "metrics": {"set_recall_at_10": recall},
                "candidate_ranked_results": [
                    {"paper_id": paper_id} for paper_id in (candidates or [])
                ],
            }
        ]
    }


def test_retriever_config_rejects_unknown_and_invalid_controls() -> None:
    with pytest.raises(ValueError, match="unknown retriever"):
        RetrieverConfig.from_mapping({"not_a_control": True})
    with pytest.raises(ValueError, match="non-negative"):
        RetrieverConfig(keyword_weight=-1.0)
    with pytest.raises(ValueError, match="at least one"):
        RetrieverConfig(keyword_weight=0.0, vector_weight=0.0)


def test_baseline_config_disables_every_heuristic_component() -> None:
    assert BASELINE_RETRIEVER_CONFIG.enable_query_expansion is False
    assert BASELINE_RETRIEVER_CONFIG.enable_metadata_boost is False
    assert BASELINE_RETRIEVER_CONFIG.enable_section_boost is False
    assert BASELINE_RETRIEVER_CONFIG.enable_evidence_adjustment is False
    assert BASELINE_RETRIEVER_CONFIG.enable_topic_adjustment is False
    assert BASELINE_RETRIEVER_CONFIG.enable_diversity_penalty is False


def test_component_ranking_respects_weight_and_metadata_toggle() -> None:
    keyword = [
        {
            "chunk_id": "a-1",
            "paper_id": "a",
            "paper_title": "Unrelated title",
            "score": 0.9,
            "snippet": "plain text",
        },
        {
            "chunk_id": "b-1",
            "paper_id": "b",
            "paper_title": "Exact climate title",
            "score": 0.8,
            "snippet": "plain text",
        },
    ]
    no_metadata = RetrieverConfig(
        enable_query_expansion=False,
        enable_metadata_boost=False,
        enable_section_boost=False,
        enable_evidence_adjustment=False,
        enable_topic_adjustment=False,
        enable_diversity_penalty=False,
        keyword_weight=1.0,
        vector_weight=1.0,
    )
    with_metadata = RetrieverConfig.from_mapping(
        {**no_metadata.to_dict(), "enable_metadata_boost": True, "metadata_scale": 3.0}
    )

    baseline = rank_retrieval_components(
        keyword,
        [],
        mode="hybrid",
        top_k=2,
        query="climate",
        config=no_metadata,
    )
    boosted = rank_retrieval_components(
        keyword,
        [],
        mode="hybrid",
        top_k=2,
        query="climate",
        config=with_metadata,
    )

    assert [row["paper_id"] for row in baseline] == ["a", "b"]
    assert [row["paper_id"] for row in boosted] == ["b", "a"]
    assert boosted[0]["scores"]["metadata"] > 0


def test_evaluator_captures_nested_runtime_scores() -> None:
    rows = capture_ranking_rows(
        [
            {
                "paper_id": "a",
                "chunk_id": "a-1",
                "page_start": 1,
                "page_end": 2,
                "section": "Results",
                "scores": {
                    "combined": 0.9,
                    "keyword": 0.5,
                    "semantic": 0.4,
                    "metadata": 0.1,
                    "diversity_penalty": 0.05,
                },
            }
        ]
    )

    assert rows[0]["score"] == 0.9
    assert rows[0]["keyword_score"] == 0.5
    assert rows[0]["semantic_score"] == 0.4
    assert rows[0]["metadata_score"] == 0.1
    assert rows[0]["diversity_penalty"] == 0.05


def test_split_is_frozen_and_disjoint() -> None:
    questions = [
        *({"case_id": f"d-{index}", "split": "dev"} for index in range(30)),
        *({"case_id": f"t-{index}", "split": "test"} for index in range(20)),
    ]
    dev, test = split_questions(questions)

    assert len(dev) == 30
    assert len(test) == 20
    assert {row["case_id"] for row in dev}.isdisjoint({row["case_id"] for row in test})


def test_tuning_selection_uses_declared_dev_metrics_and_tie_break() -> None:
    first = {
        "metrics": {"mrr": 0.5, "ndcg_at_10": 0.6, "set_recall_at_10": 0.7}
    }
    better = {
        "metrics": {"mrr": 0.6, "ndcg_at_10": 0.5, "set_recall_at_10": 0.5}
    }
    selected_id, selected = select_tuned_configuration(
        [
            ("first", DEFAULT_RETRIEVER_CONFIG, first),
            ("better", RetrieverConfig(keyword_weight=0.3, vector_weight=0.6), better),
        ]
    )

    assert selected_id == "better"
    assert selected.keyword_weight == 0.3


def test_error_taxonomy_uses_measured_counterfactual_signals() -> None:
    question = {
        "case_id": "q1",
        "category": "topic_application",
        "answerability": "answerable",
        "relevant_paper_ids": ["relevant"],
        "supporting_evidence": [{"section": "Unknown"}],
    }
    taxonomy = error_taxonomy(
        [question],
        tuned=result("q1", 0.0, candidates=["relevant"]),
        keyword=result("q1", 0.0),
        dense=result("q1", 1.0),
        no_expansion=result("q1", 1.0),
        no_diversity=result("q1", 1.0),
    )
    tags = {item["type"] for item in taxonomy["cases"][0]["diagnostic_tags"]}

    assert {
        "extraction",
        "intent_mismatch",
        "lexical_mismatch",
        "topic_identity_error",
        "over_broad_expansion",
        "ranking_diversity",
    } <= tags
    assert taxonomy["taxonomy"]["semantic_mismatch"]["case_count"] == 0
