from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.evaluation.qa_faithfulness_eval import calculate_faithfulness_metrics, load_jsonl, segment_atomic_claims


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_qa_faithfulness_v1",
    ROOT / "data" / "evaluation" / "validate_qa_faithfulness_v1.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
REVIEW_SPEC = importlib.util.spec_from_file_location(
    "review_qa_faithfulness_v1",
    ROOT / "data" / "evaluation" / "review_qa_faithfulness_v1.py",
)
assert REVIEW_SPEC is not None and REVIEW_SPEC.loader is not None
REVIEWER = importlib.util.module_from_spec(REVIEW_SPEC)
REVIEW_SPEC.loader.exec_module(REVIEWER)


def test_claim_segmenter_ignores_paper_bibliography_markers_and_splits_authorship() -> None:
    chunk_id = "paper-chunk-0001"
    result = segment_atomic_claims(
        "- Pat Researcher: appears on First Paper; Second Paper. [12] " f"[{chunk_id}]",
        case_id="qa-silver-001",
        source_map={chunk_id: chunk_id},
    )

    assert [claim["text"] for claim in result["claims"]] == [
        'Pat Researcher authored or co-authored "First Paper"',
        'Pat Researcher authored or co-authored "Second Paper"',
    ]
    assert all(claim["inline_source_ids"] == [chunk_id] for claim in result["claims"])


def test_claim_segmenter_detects_explicit_abstention() -> None:
    result = segment_atomic_claims(
        "I could not answer this from the indexed TTLAB papers.",
        case_id="qa-silver-050",
    )

    assert result["did_abstain"] is True
    assert result["claims"] == []


def test_faithfulness_metrics_keep_support_coverage_and_abstention_distinct() -> None:
    rows = [
        _row(
            "qa-silver-001",
            answerability="answerable",
            did_abstain=False,
            support="supported",
            citation="correct",
            point="covered",
        ),
        _row(
            "qa-silver-002",
            answerability="answerable",
            did_abstain=False,
            support="supported",
            citation="partially_correct",
            point="not_covered",
        ),
        _row(
            "qa-silver-003",
            answerability="unanswerable",
            did_abstain=False,
            support="supported",
            citation="correct",
            point=None,
        ),
    ]

    result = calculate_faithfulness_metrics(rows)

    assert result["metrics"]["supported_claim_rate"] == 1.0
    assert result["metrics"]["citation_precision_correctness"] == 0.666667
    assert result["metrics"]["citation_completeness"] == 1.0
    assert result["metrics"]["answer_point_coverage"] == 0.5
    assert result["metrics"]["abstention_accuracy"] == 0.666667
    assert result["metrics"]["unanswerable_abstention_rate"] == 0.0


def test_result_schema_allows_a_verified_pre_generation_abstention() -> None:
    row = copy.deepcopy(load_jsonl(ROOT / "data/evaluation/qa_faithfulness_results_v1.jsonl")[-1])
    row.update(
        {
            "provider": "not_invoked",
            "model": "not_invoked",
            "did_abstain": True,
            "returned_citation_ids": [],
            "adjudicated_claims": [],
            "adjudicated_answer_points": [],
        }
    )
    row["creation_review"].update({"did_abstain": True, "claim_judgments": [], "answer_point_judgments": []})
    row["verification_review"].update(
        {"did_abstain": True, "claim_judgments": [], "answer_point_judgments": []}
    )

    VALIDATOR._validate_schema(
        [row],
        ROOT / "data/evaluation/qa_faithfulness_results_v1.schema.json",
    )


def test_result_schema_rejects_not_invoked_for_a_non_abstaining_answer() -> None:
    row = copy.deepcopy(load_jsonl(ROOT / "data/evaluation/qa_faithfulness_results_v1.jsonl")[-1])
    row.update({"provider": "not_invoked", "model": "not_invoked", "did_abstain": False})

    with pytest.raises(AssertionError):
        VALIDATOR._validate_schema(
            [row],
            ROOT / "data/evaluation/qa_faithfulness_results_v1.schema.json",
        )


def test_answer_contract_accepts_a_provider_not_invoked_abstention() -> None:
    row, answer, raw = _contract_records(did_abstain=True, provider="not_invoked", model="not_invoked")

    VALIDATOR._validate_answer_contract(row, answer, raw)


def test_answer_contract_accepts_the_pinned_generated_identity() -> None:
    row, answer, raw = _contract_records(
        did_abstain=False,
        provider="offline_extractive",
        model="sentence-overlap-v1",
    )

    VALIDATOR._validate_answer_contract(row, answer, raw)


def test_answer_contract_rejects_scope_drift() -> None:
    row, answer, raw = _contract_records(did_abstain=True, provider="not_invoked", model="not_invoked")
    raw["request"]["retrieval_scope"] = "public"

    with pytest.raises(AssertionError, match="request scope mismatch"):
        VALIDATOR._validate_answer_contract(row, answer, raw)


def test_answer_identity_summary_separates_configuration_from_observed_non_invocation() -> None:
    summary = REVIEWER._answer_identity_summary(
        [
            {
                "qa_case_id": "qa-silver-001",
                "provider": "offline_extractive",
                "model": "sentence-overlap-v1",
            },
            {"qa_case_id": "qa-silver-050", "provider": "not_invoked", "model": "not_invoked"},
        ]
    )

    assert summary["configured_answer_provider"] == "offline_extractive"
    assert summary["configured_answer_model"] == "sentence-overlap-v1"
    assert summary["observed_answer_providers"] == {"not_invoked": 1, "offline_extractive": 1}
    assert summary["observed_answer_models"] == {"not_invoked": 1, "sentence-overlap-v1": 1}
    assert summary["provider_not_invoked_case_ids"] == ["qa-silver-050"]


def _row(
    case_id: str,
    *,
    answerability: str,
    did_abstain: bool,
    support: str,
    citation: str,
    point: str | None,
) -> dict:
    claim = {
        "claim_id": f"{case_id}-claim-001",
        "checkable_corpus_claim": True,
        "support_label": support,
        "inline_source_ids": ["chunk-1"],
        "citation_judgments": [
            {"source_id": "chunk-1", "citation_label": citation},
        ],
        "unsupported_general_knowledge": False,
        "error_codes": [],
    }
    point_rows = [] if point is None else [{"answer_point_id": f"{case_id}-point-01", "coverage_label": point}]
    review = {
        "did_abstain": did_abstain,
        "claim_judgments": [claim],
        "answer_point_judgments": point_rows,
    }
    return {
        "qa_case_id": case_id,
        "category": "test",
        "answerability": answerability,
        "did_abstain": did_abstain,
        "returned_citation_ids": ["chunk-1"],
        "adjudicated_claims": [claim],
        "adjudicated_answer_points": point_rows,
        "case_error_codes": [],
        "creation_review": review,
        "verification_review": review,
    }


def _contract_records(*, did_abstain: bool, provider: str, model: str) -> tuple[dict, dict, dict]:
    case_id = "qa-silver-050"
    question = "Which indexed paper reports a randomized clinical trial?"
    answer_text = (
        "I could not answer this from the indexed TTLAB papers."
        if did_abstain
        else "The indexed evidence reports a bounded result. [chunk-1]"
    )
    answer_sha256 = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    citation_ids = [] if provider == "not_invoked" else ["chunk-1"]
    answerability = provider != "not_invoked"
    resolution = {
        "requested_provider": "offline_extractive",
        "requested_model": None,
        "configured_provider": "offline_extractive",
        "configured_model": "sentence-overlap-v1",
        "effective_provider": provider,
        "effective_model": None if provider == "not_invoked" else model,
        "fallback_used": False,
    }
    review = {"did_abstain": did_abstain}
    row = {
        "qa_case_id": case_id,
        "question": question,
        "answer": answer_text,
        "answer_sha256": answer_sha256,
        "provider": provider,
        "model": model,
        "retrieval_mode": "hybrid",
        "top_k": 5,
        "returned_citation_ids": citation_ids,
        "did_abstain": did_abstain,
        "creation_review": review,
        "verification_review": review,
        "adjudicated_claims": [],
    }
    answer = {
        "qa_case_id": case_id,
        "question": question,
        "answer": answer_text,
        "answer_sha256": answer_sha256,
        "provider": provider,
        "model": model,
        "requested_provider": "offline_extractive",
        "requested_model": None,
        "retrieval_mode": "hybrid",
        "top_k": 5,
        "returned_citation_ids": citation_ids,
        "did_abstain": did_abstain,
        "segmentation": {"did_abstain": did_abstain, "claims": []},
        "retrieval_metadata": {"retrieval_scope": "technical"},
    }
    raw = {
        "qa_case_id": case_id,
        "request": {
            "question": question,
            "provider": "offline_extractive",
            "model": None,
            "mode": "hybrid",
            "top_k": 5,
            "retrieval_scope": "technical",
        },
        "response": {
            "question": question,
            "answer": answer_text,
            "provider": provider,
            "model": model,
            "retrieval_mode": "hybrid",
            "top_k": 5,
            "citations": [{"chunk_id": chunk_id} for chunk_id in citation_ids],
            "retrieval_metadata": {"retrieval_scope": "technical"},
            "generation_metadata": {"provider_resolution": resolution},
            "answerability": {"answerable": answerability},
            "grounding_status": "unsupported" if did_abstain else "partial",
        },
    }
    return row, answer, raw
