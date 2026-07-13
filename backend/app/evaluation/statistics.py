from __future__ import annotations

import itertools
import math
import random
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated empirical percentile.

    The definition is explicit so result files do not depend on a NumPy version's
    percentile defaults.
    """

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    repetitions: int = 10_000,
    confidence_level: float = 0.95,
    seed: int = 20260712,
    retain_replicates: bool = True,
) -> dict[str, Any]:
    """Percentile bootstrap CI for a query-level arithmetic mean.

    Each replicate resamples whole queries with replacement. This estimates
    uncertainty over this query sample; it does not account for silver-label
    error or corpus sampling.
    """

    sample = [float(value) for value in values]
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if not sample:
        return {
            "method": "query_bootstrap_percentile",
            "unit": "query",
            "sample_size": 0,
            "estimate": None,
            "confidence_level": confidence_level,
            "ci_lower": None,
            "ci_upper": None,
            "repetitions": repetitions,
            "seed": seed,
            "replicate_means": [] if retain_replicates else None,
        }

    generator = random.Random(seed)
    size = len(sample)
    replicate_means = [
        fmean(sample[generator.randrange(size)] for _ in range(size))
        for _ in range(repetitions)
    ]
    tail = (1.0 - confidence_level) / 2.0
    return {
        "method": "query_bootstrap_percentile",
        "unit": "query",
        "sample_size": size,
        "estimate": fmean(sample),
        "confidence_level": confidence_level,
        "ci_lower": percentile(replicate_means, tail),
        "ci_upper": percentile(replicate_means, 1.0 - tail),
        "repetitions": repetitions,
        "seed": seed,
        "replicate_means": replicate_means if retain_replicates else None,
    }


def paired_bootstrap_mean_difference(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    repetitions: int = 10_000,
    confidence_level: float = 0.95,
    seed: int = 20260712,
    retain_replicates: bool = True,
) -> dict[str, Any]:
    """Query-paired bootstrap CI for candidate minus baseline mean."""

    left, right = _validate_pairs(baseline, candidate)
    differences = [right_value - left_value for left_value, right_value in zip(left, right, strict=True)]
    result = bootstrap_mean_interval(
        differences,
        repetitions=repetitions,
        confidence_level=confidence_level,
        seed=seed,
        retain_replicates=retain_replicates,
    )
    return {
        **result,
        "method": "query_paired_bootstrap_percentile",
        "contrast": "candidate_minus_baseline",
    }


def paired_permutation_test(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    seed: int = 20260712,
    monte_carlo_repetitions: int = 100_000,
    exact_pair_limit: int = 20,
) -> dict[str, Any]:
    """Two-sided paired randomization test on the mean difference.

    Under the sharp exchangeability null, each non-zero within-query difference
    can have its sign flipped. Tests are exact up to ``exact_pair_limit``
    non-zero pairs and use a fixed-seed Monte Carlo estimate otherwise.
    """

    left, right = _validate_pairs(baseline, candidate)
    differences = [right_value - left_value for left_value, right_value in zip(left, right, strict=True)]
    nonzero = [difference for difference in differences if not math.isclose(difference, 0.0, abs_tol=1e-15)]
    observed = fmean(differences)
    observed_absolute_sum = abs(sum(nonzero))
    tolerance = 1e-15

    if not nonzero:
        return {
            "method": "paired_randomization_exact",
            "alternative": "two-sided",
            "pair_count": len(differences),
            "nonzero_pair_count": 0,
            "mean_difference": observed,
            "p_value": 1.0,
            "seed": None,
            "randomizations": 1,
            "assumption": "Within-query method labels are exchangeable under the sharp null.",
        }

    if len(nonzero) <= exact_pair_limit:
        extreme = 0
        randomizations = 2 ** len(nonzero)
        for signs in itertools.product((-1.0, 1.0), repeat=len(nonzero)):
            randomized_absolute_sum = abs(sum(sign * difference for sign, difference in zip(signs, nonzero, strict=True)))
            if randomized_absolute_sum + tolerance >= observed_absolute_sum:
                extreme += 1
        p_value = extreme / randomizations
        method = "paired_randomization_exact"
        used_seed: int | None = None
    else:
        if monte_carlo_repetitions < 1:
            raise ValueError("monte_carlo_repetitions must be at least 1")
        generator = random.Random(seed)
        extreme = 0
        for _ in range(monte_carlo_repetitions):
            randomized_absolute_sum = abs(
                sum((1.0 if generator.random() < 0.5 else -1.0) * difference for difference in nonzero)
            )
            if randomized_absolute_sum + tolerance >= observed_absolute_sum:
                extreme += 1
        # Plus-one correction prevents a zero Monte Carlo p-value.
        p_value = (extreme + 1) / (monte_carlo_repetitions + 1)
        randomizations = monte_carlo_repetitions
        method = "paired_randomization_monte_carlo"
        used_seed = seed

    return {
        "method": method,
        "alternative": "two-sided",
        "pair_count": len(differences),
        "nonzero_pair_count": len(nonzero),
        "mean_difference": observed,
        "p_value": p_value,
        "seed": used_seed,
        "randomizations": randomizations,
        "assumption": "Within-query method labels are exchangeable under the sharp null.",
    }


def holm_bonferroni(
    p_values: Mapping[str, float],
    *,
    familywise_alpha: float = 0.05,
) -> dict[str, dict[str, Any]]:
    """Holm step-down family-wise error correction with adjusted p-values."""

    if not 0.0 < familywise_alpha < 1.0:
        raise ValueError("familywise_alpha must be between 0 and 1")
    validated: list[tuple[str, float]] = []
    for label, raw_value in p_values.items():
        value = float(raw_value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"p-value for {label!r} must be between 0 and 1")
        validated.append((str(label), value))

    ordered = sorted(validated, key=lambda item: (item[1], item[0]))
    total = len(ordered)
    adjusted_by_label: dict[str, float] = {}
    running_adjusted = 0.0
    continue_rejecting = True
    rejected_by_label: dict[str, bool] = {}
    threshold_by_label: dict[str, float] = {}
    for index, (label, value) in enumerate(ordered):
        remaining = total - index
        adjusted = min(1.0, max(running_adjusted, remaining * value))
        running_adjusted = adjusted
        adjusted_by_label[label] = adjusted
        threshold = familywise_alpha / remaining
        threshold_by_label[label] = threshold
        rejected = continue_rejecting and value <= threshold
        rejected_by_label[label] = rejected
        if not rejected:
            continue_rejecting = False

    return {
        label: {
            "raw_p_value": value,
            "adjusted_p_value": adjusted_by_label[label],
            "holm_threshold": threshold_by_label[label],
            "reject_null": rejected_by_label[label],
            "familywise_alpha": familywise_alpha,
        }
        for label, value in validated
    }


def compare_paired_runs(
    baseline_rows: Iterable[Mapping[str, Any]],
    candidate_rows: Iterable[Mapping[str, Any]],
    *,
    metric: str,
    repetitions: int = 10_000,
    seed: int = 20260712,
) -> dict[str, Any]:
    """Compare one per-query metric over two runs with identical case IDs."""

    baseline = _rows_by_case_id(baseline_rows)
    candidate = _rows_by_case_id(candidate_rows)
    if set(baseline) != set(candidate):
        missing_from_candidate = sorted(set(baseline) - set(candidate))
        missing_from_baseline = sorted(set(candidate) - set(baseline))
        raise ValueError(
            "paired runs must contain identical case IDs; "
            f"missing_from_candidate={missing_from_candidate} missing_from_baseline={missing_from_baseline}"
        )

    case_ids: list[str] = []
    baseline_values: list[float] = []
    candidate_values: list[float] = []
    omitted_case_ids: list[str] = []
    for case_id in sorted(baseline):
        baseline_value = _metric_value(baseline[case_id], metric)
        candidate_value = _metric_value(candidate[case_id], metric)
        if baseline_value is None or candidate_value is None:
            omitted_case_ids.append(case_id)
            continue
        case_ids.append(case_id)
        baseline_values.append(float(baseline_value))
        candidate_values.append(float(candidate_value))
    if not case_ids:
        raise ValueError(f"no paired numeric values found for metric {metric!r}")

    return {
        "metric": metric,
        "case_ids": case_ids,
        "omitted_case_ids": omitted_case_ids,
        "paired_query_count": len(case_ids),
        "baseline_mean": fmean(baseline_values),
        "candidate_mean": fmean(candidate_values),
        "mean_difference": fmean(candidate_values) - fmean(baseline_values),
        "confidence_interval": paired_bootstrap_mean_difference(
            baseline_values,
            candidate_values,
            repetitions=repetitions,
            seed=seed,
        ),
        "paired_test": paired_permutation_test(baseline_values, candidate_values, seed=seed),
    }


def _validate_pairs(baseline: Sequence[float], candidate: Sequence[float]) -> tuple[list[float], list[float]]:
    left = [float(value) for value in baseline]
    right = [float(value) for value in candidate]
    if not left:
        raise ValueError("paired analysis requires at least one pair")
    if len(left) != len(right):
        raise ValueError("baseline and candidate must have the same length")
    return left, right


def _rows_by_case_id(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if not case_id:
            raise ValueError("every paired result row must have a case_id")
        if case_id in indexed:
            raise ValueError(f"duplicate case_id in paired run: {case_id}")
        indexed[case_id] = row
    return indexed


def _metric_value(row: Mapping[str, Any], metric: str) -> float | int | bool | None:
    metrics = row.get("metrics")
    if isinstance(metrics, Mapping):
        per_query_name = {
            "mrr": "reciprocal_rank",
            "unanswerable_abstention_rate": "unanswerable_abstention",
            "unanswerable_false_positive_rate": "unanswerable_false_positive",
        }.get(metric, metric)
        value = metrics.get(per_query_name, metrics.get(metric))
    else:
        value = row.get(metric)
    if value is None or isinstance(value, (float, int, bool)):
        return value
    raise ValueError(f"metric {metric!r} must be numeric, boolean, or null")
