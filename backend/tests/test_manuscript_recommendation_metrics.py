from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.recommendation_manuscript_metrics import (
    RecommendationManuscriptMetricsError,
    derive_recommendation_manuscript_metrics,
)


def current_aggregate() -> dict:
    return {
        "profile_coverage": {"profile_count": 2},
        "metrics": {
            "arm_comparison": {
                "profile_count": 2,
                "requested_cutoff": 3,
                "expected_ranked_slots_per_arm": 6,
                "returned_ranked_items": {
                    "evidence_only": 6,
                    "full_finder": 3,
                },
            },
            "ranking_coverage": {
                "requested_cutoff": 3,
                "profile_count": 2,
                "short_rankings_preserved": True,
                "missing_slots_are_not_imputed": True,
                "arms": {
                    "evidence_only": {
                        "returned_items": 6,
                        "expected_slots": 6,
                        "missing_slots": 0,
                        "return_coverage": 1.0,
                        "profiles_at_cutoff": 2,
                        "short_profiles": [],
                        "shortfall_slots": [],
                    },
                    "full_finder": {
                        "returned_items": 3,
                        "expected_slots": 6,
                        "missing_slots": 3,
                        "return_coverage": 0.5,
                        "profiles_at_cutoff": 0,
                        "short_profiles": [
                            {
                                "profile_id": "profile-1",
                                "returned_items": 1,
                                "missing_ranks": [2, 3],
                            },
                            {
                                "profile_id": "profile-2",
                                "returned_items": 2,
                                "missing_ranks": [3],
                            },
                        ],
                        "shortfall_slots": [
                            {"slot_id": "profile-1:full_finder:2"},
                            {"slot_id": "profile-1:full_finder:3"},
                            {"slot_id": "profile-2:full_finder:3"},
                        ],
                    },
                },
            },
            "evidence_only": {
                "reviewed_items": 6,
                "criteria": {
                    "paper_relevance": {"counts": {"pass": 6}},
                    "source_fidelity": {"counts": {"pass": 6}},
                },
            },
            "full_finder": {
                "reviewed_items": 3,
                "criteria": {
                    "source_fidelity": {"counts": {"pass": 3}},
                    "fact_future_gap_suggestion_separation": {
                        "counts": {"pass": 2, "fail": 1}
                    },
                    "skills_time_data_feasibility": {"counts": {"fail": 3}},
                    "evaluation_plan_quality": {
                        "counts": {"pass": 1, "partial": 1, "fail": 1}
                    },
                },
            },
        },
    }


def legacy_complete_aggregate() -> dict:
    aggregate = current_aggregate()
    del aggregate["metrics"]["ranking_coverage"]
    aggregate["metrics"]["full_finder"]["reviewed_items"] = 6
    for criterion in aggregate["metrics"]["full_finder"]["criteria"].values():
        criterion["counts"] = {"pass": 6}
    aggregate["metrics"]["arm_comparison"].pop("requested_cutoff")
    aggregate["metrics"]["arm_comparison"].pop("expected_ranked_slots_per_arm")
    aggregate["metrics"]["arm_comparison"].pop("returned_ranked_items")
    return aggregate


def test_derives_asymmetric_coverage_and_sparse_judgment_buckets() -> None:
    derived = derive_recommendation_manuscript_metrics(current_aggregate())

    assert derived["coverage_source"] == "metrics.ranking_coverage"
    assert derived["layout_fallback_used"] is False
    assert derived["final_evidence_eligible"] is True
    assert derived["profile_count"] == 2
    assert derived["requested_cutoff"] == 3
    assert derived["requested_slots_per_arm"] == 6
    assert derived["arms"]["evidence_only"] == {
        "returned_items": 6,
        "missing_slots": 0,
        "return_coverage": 1.0,
        "profiles_at_cutoff": 2,
        "short_profile_count": 0,
        "short_profile_ids": [],
        "criteria": {
            "paper_relevance": {"pass": 6, "partial": 0, "fail": 0},
            "source_fidelity": {"pass": 6, "partial": 0, "fail": 0},
        },
    }
    full = derived["arms"]["full_finder"]
    assert full["returned_items"] == 3
    assert full["missing_slots"] == 3
    assert full["return_coverage"] == pytest.approx(0.5)
    assert full["profiles_at_cutoff"] == 0
    assert full["short_profile_count"] == 2
    assert full["short_profile_ids"] == ["profile-1", "profile-2"]
    assert full["criteria"]["skills_time_data_feasibility"] == {
        "pass": 0,
        "partial": 0,
        "fail": 3,
    }
    assert full["criteria"]["evaluation_plan_quality"] == {
        "pass": 1,
        "partial": 1,
        "fail": 1,
    }


def test_final_mode_rejects_legacy_aggregate_without_ranking_coverage() -> None:
    with pytest.raises(
        RecommendationManuscriptMetricsError,
        match="ranking_coverage is required for final manuscript evidence",
    ):
        derive_recommendation_manuscript_metrics(legacy_complete_aggregate())


def test_explicit_layout_fallback_is_marked_ineligible_for_final_evidence() -> None:
    derived = derive_recommendation_manuscript_metrics(
        legacy_complete_aggregate(),
        allow_layout_fallback=True,
    )

    assert derived["coverage_source"] == "legacy_layout_fallback"
    assert derived["layout_fallback_used"] is True
    assert derived["final_evidence_eligible"] is False
    assert derived["use_scope"] == "layout_only"
    assert derived["requested_slots_per_arm"] == 6
    assert derived["arms"]["full_finder"]["profiles_at_cutoff"] == 2


def test_layout_fallback_rejects_short_rankings_it_cannot_reconstruct() -> None:
    aggregate = legacy_complete_aggregate()
    aggregate["metrics"]["full_finder"]["reviewed_items"] = 3
    for criterion in aggregate["metrics"]["full_finder"]["criteria"].values():
        criterion["counts"] = {"fail": 3}

    with pytest.raises(
        RecommendationManuscriptMetricsError,
        match="cannot infer profiles_at_cutoff",
    ):
        derive_recommendation_manuscript_metrics(
            aggregate,
            allow_layout_fallback=True,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: (
                value["metrics"]["full_finder"].update(reviewed_items=4),
                [
                    criterion.update(counts={"pass": 4})
                    for criterion in value["metrics"]["full_finder"][
                        "criteria"
                    ].values()
                ],
            ),
            "returned_items=3",
        ),
        (
            lambda value: value["metrics"]["ranking_coverage"]["arms"][
                "full_finder"
            ].update(missing_slots=2),
            "missing_slots is inconsistent",
        ),
        (
            lambda value: value["metrics"]["ranking_coverage"]["arms"][
                "full_finder"
            ].update(return_coverage=0.75),
            "return_coverage=0.75",
        ),
        (
            lambda value: value["metrics"]["full_finder"]["criteria"][
                "skills_time_data_feasibility"
            ].update(counts={"fail": 2}),
            "counts totals 2",
        ),
        (
            lambda value: value["metrics"]["ranking_coverage"]["arms"][
                "full_finder"
            ].update(profiles_at_cutoff=1),
            "short_profiles count is inconsistent",
        ),
    ],
)
def test_rejects_inconsistent_aggregate_totals(mutate, message: str) -> None:
    aggregate = deepcopy(current_aggregate())
    mutate(aggregate)

    with pytest.raises(RecommendationManuscriptMetricsError, match=message):
        derive_recommendation_manuscript_metrics(aggregate)
