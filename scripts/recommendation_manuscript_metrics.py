"""Validate and normalize recommendation evidence used by manuscript generators.

The historical recommendation aggregate predates explicit ranking-coverage
evidence.  Final manuscript generation must use the current aggregate shape and
therefore leaves ``allow_layout_fallback`` disabled.  The opt-in fallback exists
only so layout-only builds can still be exercised before fresh evidence is
available; its result is marked as ineligible for final evidence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


ARMS = ("evidence_only", "full_finder")
JUDGMENT_BUCKETS = ("pass", "partial", "fail")


class RecommendationManuscriptMetricsError(ValueError):
    """Raised when recommendation evidence is missing or internally inconsistent."""


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecommendationManuscriptMetricsError(f"{path} must be an object")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecommendationManuscriptMetricsError(
            f"{path} must be an integer >= {minimum}"
        )
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecommendationManuscriptMetricsError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RecommendationManuscriptMetricsError(f"{path} must be finite")
    return result


def _reviewed_items(metrics: Mapping[str, Any], arm: str) -> int:
    arm_metrics = _mapping(metrics.get(arm), f"metrics.{arm}")
    return _integer(
        arm_metrics.get("reviewed_items"),
        f"metrics.{arm}.reviewed_items",
    )


def _criterion_buckets(
    metrics: Mapping[str, Any],
    arm: str,
    *,
    reviewed_items: int,
) -> dict[str, dict[str, int]]:
    arm_metrics = _mapping(metrics.get(arm), f"metrics.{arm}")
    criteria = _mapping(arm_metrics.get("criteria"), f"metrics.{arm}.criteria")
    if not criteria:
        raise RecommendationManuscriptMetricsError(
            f"metrics.{arm}.criteria must contain at least one criterion"
        )

    normalized: dict[str, dict[str, int]] = {}
    for criterion, raw_value in criteria.items():
        if not isinstance(criterion, str) or not criterion:
            raise RecommendationManuscriptMetricsError(
                f"metrics.{arm}.criteria keys must be non-empty strings"
            )
        criterion_value = _mapping(
            raw_value,
            f"metrics.{arm}.criteria.{criterion}",
        )
        counts = _mapping(
            criterion_value.get("counts"),
            f"metrics.{arm}.criteria.{criterion}.counts",
        )
        unknown = sorted(set(counts) - set(JUDGMENT_BUCKETS))
        if unknown:
            raise RecommendationManuscriptMetricsError(
                f"metrics.{arm}.criteria.{criterion}.counts has unsupported "
                f"buckets: {unknown}"
            )
        buckets = {
            bucket: _integer(
                counts.get(bucket, 0),
                f"metrics.{arm}.criteria.{criterion}.counts.{bucket}",
            )
            for bucket in JUDGMENT_BUCKETS
        }
        if sum(buckets.values()) != reviewed_items:
            raise RecommendationManuscriptMetricsError(
                f"metrics.{arm}.criteria.{criterion}.counts totals "
                f"{sum(buckets.values())}, expected reviewed_items={reviewed_items}"
            )
        normalized[criterion] = buckets
    return normalized


def _cross_check_profile_count(
    aggregate: Mapping[str, Any],
    comparison: Mapping[str, Any],
    profile_count: int,
) -> None:
    comparison_count = comparison.get("profile_count")
    if comparison_count is not None and _integer(
        comparison_count,
        "metrics.arm_comparison.profile_count",
        minimum=1,
    ) != profile_count:
        raise RecommendationManuscriptMetricsError(
            "metrics.arm_comparison.profile_count disagrees with ranking coverage"
        )

    profile_coverage = aggregate.get("profile_coverage")
    if profile_coverage is not None:
        covered_count = _integer(
            _mapping(profile_coverage, "profile_coverage").get("profile_count"),
            "profile_coverage.profile_count",
            minimum=1,
        )
        if covered_count != profile_count:
            raise RecommendationManuscriptMetricsError(
                "profile_coverage.profile_count disagrees with ranking coverage"
            )


def _validate_comparison(
    comparison: Mapping[str, Any],
    *,
    requested_cutoff: int,
    expected_slots: int,
    returned_by_arm: Mapping[str, int],
) -> None:
    comparison_cutoff = comparison.get("requested_cutoff")
    if comparison_cutoff is not None and _integer(
        comparison_cutoff,
        "metrics.arm_comparison.requested_cutoff",
        minimum=1,
    ) != requested_cutoff:
        raise RecommendationManuscriptMetricsError(
            "metrics.arm_comparison.requested_cutoff disagrees with ranking coverage"
        )

    comparison_slots = comparison.get("expected_ranked_slots_per_arm")
    if comparison_slots is not None and _integer(
        comparison_slots,
        "metrics.arm_comparison.expected_ranked_slots_per_arm",
        minimum=1,
    ) != expected_slots:
        raise RecommendationManuscriptMetricsError(
            "metrics.arm_comparison.expected_ranked_slots_per_arm disagrees with "
            "ranking coverage"
        )

    comparison_returned = comparison.get("returned_ranked_items")
    if comparison_returned is not None:
        returned = _mapping(
            comparison_returned,
            "metrics.arm_comparison.returned_ranked_items",
        )
        for arm in ARMS:
            if _integer(
                returned.get(arm),
                f"metrics.arm_comparison.returned_ranked_items.{arm}",
            ) != returned_by_arm[arm]:
                raise RecommendationManuscriptMetricsError(
                    f"metrics.arm_comparison.returned_ranked_items.{arm} "
                    "disagrees with ranking coverage"
                )


def _coverage_arm(
    raw_arm: Any,
    *,
    arm: str,
    profile_count: int,
    requested_cutoff: int,
    expected_slots: int,
    reviewed_items: int,
    criteria: dict[str, dict[str, int]],
) -> dict[str, Any]:
    path = f"metrics.ranking_coverage.arms.{arm}"
    value = _mapping(raw_arm, path)
    returned_items = _integer(value.get("returned_items"), f"{path}.returned_items")
    arm_expected = _integer(
        value.get("expected_slots"),
        f"{path}.expected_slots",
        minimum=1,
    )
    missing_slots = _integer(value.get("missing_slots"), f"{path}.missing_slots")
    return_coverage = _number(value.get("return_coverage"), f"{path}.return_coverage")
    profiles_at_cutoff = _integer(
        value.get("profiles_at_cutoff"),
        f"{path}.profiles_at_cutoff",
    )

    if arm_expected != expected_slots:
        raise RecommendationManuscriptMetricsError(
            f"{path}.expected_slots={arm_expected}, expected {expected_slots}"
        )
    if returned_items > expected_slots:
        raise RecommendationManuscriptMetricsError(
            f"{path}.returned_items cannot exceed expected_slots"
        )
    if returned_items != reviewed_items:
        raise RecommendationManuscriptMetricsError(
            f"{path}.returned_items={returned_items}, but "
            f"metrics.{arm}.reviewed_items={reviewed_items}"
        )
    if missing_slots != expected_slots - returned_items:
        raise RecommendationManuscriptMetricsError(
            f"{path}.missing_slots is inconsistent with expected and returned counts"
        )
    expected_coverage = returned_items / expected_slots
    if not math.isclose(return_coverage, expected_coverage, rel_tol=0.0, abs_tol=1e-12):
        raise RecommendationManuscriptMetricsError(
            f"{path}.return_coverage={return_coverage}, expected {expected_coverage}"
        )
    if profiles_at_cutoff > profile_count:
        raise RecommendationManuscriptMetricsError(
            f"{path}.profiles_at_cutoff cannot exceed profile_count"
        )

    short_profiles = value.get("short_profiles")
    if not isinstance(short_profiles, list):
        raise RecommendationManuscriptMetricsError(f"{path}.short_profiles must be an array")
    if len(short_profiles) != profile_count - profiles_at_cutoff:
        raise RecommendationManuscriptMetricsError(
            f"{path}.short_profiles count is inconsistent with profiles_at_cutoff"
        )

    short_profile_ids: list[str] = []
    short_returned_total = 0
    short_missing_total = 0
    for index, raw_profile in enumerate(short_profiles):
        short_path = f"{path}.short_profiles[{index}]"
        profile = _mapping(raw_profile, short_path)
        profile_id = profile.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise RecommendationManuscriptMetricsError(
                f"{short_path}.profile_id must be a non-empty string"
            )
        if profile_id in short_profile_ids:
            raise RecommendationManuscriptMetricsError(
                f"{path}.short_profiles contains duplicate profile_id={profile_id}"
            )
        profile_returned = _integer(
            profile.get("returned_items"),
            f"{short_path}.returned_items",
        )
        if profile_returned >= requested_cutoff:
            raise RecommendationManuscriptMetricsError(
                f"{short_path}.returned_items must be below requested_cutoff"
            )
        missing_ranks = profile.get("missing_ranks")
        if not isinstance(missing_ranks, list):
            raise RecommendationManuscriptMetricsError(
                f"{short_path}.missing_ranks must be an array"
            )
        if len(missing_ranks) != requested_cutoff - profile_returned:
            raise RecommendationManuscriptMetricsError(
                f"{short_path}.missing_ranks is inconsistent with returned_items"
            )
        normalized_ranks = [
            _integer(rank, f"{short_path}.missing_ranks", minimum=1)
            for rank in missing_ranks
        ]
        if len(set(normalized_ranks)) != len(normalized_ranks) or any(
            rank > requested_cutoff for rank in normalized_ranks
        ):
            raise RecommendationManuscriptMetricsError(
                f"{short_path}.missing_ranks must be unique ranks within the cutoff"
            )
        short_profile_ids.append(profile_id)
        short_returned_total += profile_returned
        short_missing_total += len(missing_ranks)

    derived_returned = profiles_at_cutoff * requested_cutoff + short_returned_total
    if derived_returned != returned_items:
        raise RecommendationManuscriptMetricsError(
            f"{path}.profiles_at_cutoff and short_profiles imply "
            f"{derived_returned} returned items, not {returned_items}"
        )
    if short_missing_total != missing_slots:
        raise RecommendationManuscriptMetricsError(
            f"{path}.short_profiles imply {short_missing_total} missing slots, "
            f"not {missing_slots}"
        )

    shortfall_slots = value.get("shortfall_slots")
    if not isinstance(shortfall_slots, list) or len(shortfall_slots) != missing_slots:
        raise RecommendationManuscriptMetricsError(
            f"{path}.shortfall_slots must enumerate every missing slot"
        )

    return {
        "returned_items": returned_items,
        "missing_slots": missing_slots,
        "return_coverage": return_coverage,
        "profiles_at_cutoff": profiles_at_cutoff,
        "short_profile_count": len(short_profiles),
        "short_profile_ids": short_profile_ids,
        "criteria": criteria,
    }


def _legacy_layout_coverage(
    aggregate: Mapping[str, Any],
    metrics: Mapping[str, Any],
    comparison: Mapping[str, Any],
    *,
    criteria_by_arm: Mapping[str, dict[str, dict[str, int]]],
    reviewed_by_arm: Mapping[str, int],
) -> dict[str, Any]:
    """Derive only the complete-ranking legacy shape used for layout previews."""

    profile_count_value = comparison.get("profile_count")
    if profile_count_value is None:
        profile_coverage = _mapping(aggregate.get("profile_coverage"), "profile_coverage")
        profile_count_value = profile_coverage.get("profile_count")
    profile_count = _integer(
        profile_count_value,
        "legacy profile_count",
        minimum=1,
    )

    expected_value = comparison.get("expected_ranked_slots_per_arm")
    if expected_value is None:
        expected_slots = reviewed_by_arm["evidence_only"]
    else:
        expected_slots = _integer(
            expected_value,
            "metrics.arm_comparison.expected_ranked_slots_per_arm",
            minimum=1,
        )
    if expected_slots % profile_count:
        raise RecommendationManuscriptMetricsError(
            "legacy layout fallback cannot derive an integer requested cutoff"
        )
    requested_cutoff = expected_slots // profile_count
    if requested_cutoff < 1:
        raise RecommendationManuscriptMetricsError(
            "legacy layout fallback derived a non-positive requested cutoff"
        )

    arms: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        returned_items = reviewed_by_arm[arm]
        if returned_items != expected_slots:
            raise RecommendationManuscriptMetricsError(
                "legacy layout fallback cannot infer profiles_at_cutoff for "
                f"short {arm} rankings; regenerate explicit ranking_coverage"
            )
        arms[arm] = {
            "returned_items": returned_items,
            "missing_slots": 0,
            "return_coverage": 1.0,
            "profiles_at_cutoff": profile_count,
            "short_profile_count": 0,
            "short_profile_ids": [],
            "criteria": criteria_by_arm[arm],
        }

    _cross_check_profile_count(aggregate, comparison, profile_count)
    _validate_comparison(
        comparison,
        requested_cutoff=requested_cutoff,
        expected_slots=expected_slots,
        returned_by_arm=reviewed_by_arm,
    )
    return {
        "coverage_source": "legacy_layout_fallback",
        "layout_fallback_used": True,
        "final_evidence_eligible": False,
        "use_scope": "layout_only",
        "profile_count": profile_count,
        "requested_cutoff": requested_cutoff,
        "requested_slots_per_arm": expected_slots,
        "arms": arms,
    }


def derive_recommendation_manuscript_metrics(
    aggregate: Mapping[str, Any],
    *,
    allow_layout_fallback: bool = False,
) -> dict[str, Any]:
    """Return validated, manuscript-ready recommendation counts.

    The default is final-evidence mode and requires ``metrics.ranking_coverage``.
    Passing ``allow_layout_fallback=True`` permits an older *complete-ranking*
    aggregate solely for layout previews.  That result carries
    ``final_evidence_eligible=False`` and must never be used for final claims.
    """

    aggregate = _mapping(aggregate, "aggregate")
    metrics = _mapping(aggregate.get("metrics"), "metrics")
    comparison = _mapping(metrics.get("arm_comparison"), "metrics.arm_comparison")
    reviewed_by_arm = {arm: _reviewed_items(metrics, arm) for arm in ARMS}
    criteria_by_arm = {
        arm: _criterion_buckets(
            metrics,
            arm,
            reviewed_items=reviewed_by_arm[arm],
        )
        for arm in ARMS
    }

    raw_coverage = metrics.get("ranking_coverage")
    if raw_coverage is None:
        if not allow_layout_fallback:
            raise RecommendationManuscriptMetricsError(
                "metrics.ranking_coverage is required for final manuscript evidence; "
                "regenerate the recommendation aggregate"
            )
        return _legacy_layout_coverage(
            aggregate,
            metrics,
            comparison,
            criteria_by_arm=criteria_by_arm,
            reviewed_by_arm=reviewed_by_arm,
        )

    coverage = _mapping(raw_coverage, "metrics.ranking_coverage")
    if coverage.get("short_rankings_preserved") is not True:
        raise RecommendationManuscriptMetricsError(
            "metrics.ranking_coverage.short_rankings_preserved must be true"
        )
    if coverage.get("missing_slots_are_not_imputed") is not True:
        raise RecommendationManuscriptMetricsError(
            "metrics.ranking_coverage.missing_slots_are_not_imputed must be true"
        )
    profile_count = _integer(
        coverage.get("profile_count"),
        "metrics.ranking_coverage.profile_count",
        minimum=1,
    )
    requested_cutoff = _integer(
        coverage.get("requested_cutoff"),
        "metrics.ranking_coverage.requested_cutoff",
        minimum=1,
    )
    expected_slots = profile_count * requested_cutoff
    coverage_arms = _mapping(coverage.get("arms"), "metrics.ranking_coverage.arms")
    arms = {
        arm: _coverage_arm(
            coverage_arms.get(arm),
            arm=arm,
            profile_count=profile_count,
            requested_cutoff=requested_cutoff,
            expected_slots=expected_slots,
            reviewed_items=reviewed_by_arm[arm],
            criteria=criteria_by_arm[arm],
        )
        for arm in ARMS
    }

    _cross_check_profile_count(aggregate, comparison, profile_count)
    _validate_comparison(
        comparison,
        requested_cutoff=requested_cutoff,
        expected_slots=expected_slots,
        returned_by_arm={arm: arms[arm]["returned_items"] for arm in ARMS},
    )
    return {
        "coverage_source": "metrics.ranking_coverage",
        "layout_fallback_used": False,
        "final_evidence_eligible": True,
        "use_scope": "final_or_layout",
        "profile_count": profile_count,
        "requested_cutoff": requested_cutoff,
        "requested_slots_per_arm": expected_slots,
        "arms": arms,
    }
