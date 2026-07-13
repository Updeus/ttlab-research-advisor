from __future__ import annotations

import pytest

from app.evaluation.performance_benchmark import percentile, summarize_samples


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([1.0, 2.0, 3.0], 0.95) == 2.9
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([], 0.95) is None


def test_summary_keeps_failures_in_failure_rate_and_omits_failed_latency() -> None:
    result = summarize_samples(
        [
            {"status": "ok", "elapsed_seconds": 1.0, "seconds_per_unit": 0.5, "max_rss_kib": 100},
            {"status": "failed", "elapsed_seconds": 99.0},
            {"status": "ok", "elapsed_seconds": 3.0, "seconds_per_unit": 1.5, "max_rss_kib": 120},
        ]
    )
    assert result["repetitions_attempted"] == 3
    assert result["repetitions_succeeded"] == 2
    assert result["failure_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["elapsed_seconds"]["median"] == 2.0
    assert result["max_rss_kib"] == 120
