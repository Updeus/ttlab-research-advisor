from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from app.evaluation import recommendation_proxy_eval as proxy_eval


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_recommendation_proxy_v1",
    ROOT / "data" / "evaluation" / "validate_recommendation_proxy_v1.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def outputs_with_safe_short_rankings() -> tuple[list[dict], list[dict]]:
    profiles = [{"profile_id": "profile-1"}, {"profile_id": "profile-2"}]
    outputs = [
        {
            "profile_id": "profile-1",
            "baseline": {
                "papers": [
                    {"rank": 1, "paper_id": "base-1a"},
                    {"rank": 2, "paper_id": "base-1b"},
                    {"rank": 3, "paper_id": "base-1c"},
                ]
            },
            "full_finder": {"recommendations": [{"rank": 1, "paper_id": "full-1a"}]},
        },
        {
            "profile_id": "profile-2",
            "baseline": {
                "papers": [
                    {"rank": 1, "paper_id": "base-2a"},
                    {"rank": 2, "paper_id": "base-2b"},
                    {"rank": 3, "paper_id": "base-2c"},
                ]
            },
            "full_finder": {
                "recommendations": [
                    {"rank": 1, "paper_id": "full-2a"},
                    {"rank": 2, "paper_id": "full-2b"},
                ]
            },
        },
    ]
    return profiles, outputs


def review_row(
    profile_id: str,
    arm: str,
    rank: int,
    paper_id: str,
    *,
    pass_number: int = 1,
) -> dict:
    return {
        "review_id": f"proxy-v1-pass{pass_number}-{profile_id}-{arm}-{rank}",
        "review_pass": pass_number,
        "profile_id": profile_id,
        "arm": arm,
        "rank": rank,
        "paper_id": paper_id,
        "judgments": {"paper_relevance": {"judgment": "pass"}},
    }


def test_ranking_coverage_preserves_and_identifies_unreturned_slots() -> None:
    profiles, outputs = outputs_with_safe_short_rankings()

    coverage = proxy_eval.summarize_ranking_coverage(profiles, outputs, top_k=3)

    full = coverage["arms"]["full_finder"]
    assert full["returned_items"] == 3
    assert full["expected_slots"] == 6
    assert full["missing_slots"] == 3
    assert full["return_coverage"] == pytest.approx(0.5)
    assert [item["slot_id"] for item in full["shortfall_slots"]] == [
        "profile-1:full_finder:2",
        "profile-1:full_finder:3",
        "profile-2:full_finder:3",
    ]
    assert coverage["missing_slots_are_not_imputed"] is True


def test_relevance_comparison_uses_requested_top_k_denominator(monkeypatch) -> None:
    profiles, outputs = outputs_with_safe_short_rankings()
    expected, _coverage = VALIDATOR.derive_expected_reviews_and_coverage(
        profiles,
        outputs,
        top_k=3,
    )
    rows = [review_row(*identity) for identity in expected]
    monkeypatch.setattr(proxy_eval, "BOOTSTRAP_REPETITIONS", 20)

    comparison = proxy_eval.compare_relevance_by_profile(
        rows,
        profile_ids=["profile-1", "profile-2"],
        top_k=3,
    )

    assert comparison["baseline_mean_relevance_score"] == pytest.approx(1.0)
    assert comparison["full_finder_mean_relevance_score"] == pytest.approx(0.5)
    assert comparison["returned_ranked_items"] == {"evidence_only": 6, "full_finder": 3}
    assert comparison["missing_ranked_slots_scored_as_zero"] is True


def test_review_pass_must_exactly_cover_emitted_item_identities() -> None:
    profiles, outputs = outputs_with_safe_short_rankings()
    expected, coverage = VALIDATOR.derive_expected_reviews_and_coverage(
        profiles,
        outputs,
        top_k=3,
    )
    rows = [review_row(*identity) for identity in expected]

    VALIDATOR.validate_review_pass_coverage(rows, expected, pass_number=1)
    assert coverage["full_finder"]["shortfall_slot_ids"] == [
        "profile-1:full_finder:2",
        "profile-1:full_finder:3",
        "profile-2:full_finder:3",
    ]

    with pytest.raises(ValueError, match="profile-2:full_finder:2:full-2b"):
        VALIDATOR.validate_review_pass_coverage(rows[:-1], expected, pass_number=1)


def test_validator_rejects_conditional_relevance_score_that_ignores_shortfall() -> None:
    profiles, outputs = outputs_with_safe_short_rankings()
    expected, derived = VALIDATOR.derive_expected_reviews_and_coverage(
        profiles,
        outputs,
        top_k=3,
    )
    rows = [review_row(*identity) for identity in expected]
    aggregate = {
        "metrics": {
            "ranking_coverage": proxy_eval.summarize_ranking_coverage(profiles, outputs, top_k=3),
            "arm_comparison": {
                "missing_ranked_slots_scored_as_zero": True,
                "expected_ranked_slots_per_arm": 6,
                "baseline_mean_relevance_score": 1.0,
                "full_finder_mean_relevance_score": 0.5,
            },
        }
    }

    VALIDATOR.validate_coverage_metrics(aggregate, profiles, rows, derived, top_k=3)

    inflated = deepcopy(aggregate)
    inflated["metrics"]["arm_comparison"]["full_finder_mean_relevance_score"] = 1.0
    with pytest.raises(ValueError, match="full_finder_mean_relevance_score"):
        VALIDATOR.validate_coverage_metrics(inflated, profiles, rows, derived, top_k=3)
