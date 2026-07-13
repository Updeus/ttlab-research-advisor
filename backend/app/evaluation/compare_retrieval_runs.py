from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.evaluation.retrieval_eval import RESULT_SCHEMA_VERSION, write_results
from app.evaluation.statistics import compare_paired_runs, holm_bonferroni


DEFAULT_COMPARISON_METRICS = (
    "set_recall_at_3",
    "set_recall_at_5",
    "set_recall_at_10",
    "hit_at_10",
    "mrr",
    "ndcg_at_10",
    "unanswerable_abstention",
)


def load_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Retrieval result file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid retrieval result JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError(f"{path} is not a retrieval evaluation result with schema {RESULT_SCHEMA_VERSION}")
    if not isinstance(payload.get("questions"), list):
        raise ValueError(f"{path} has no per-query results")
    return payload


def compare_retrieval_results(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    metrics: Sequence[str] = DEFAULT_COMPARISON_METRICS,
    repetitions: int = 10_000,
    seed: int = 20260712,
    familywise_alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired comparisons after enforcing the shared experimental controls."""

    baseline_config = _mapping(baseline.get("run_config"), "baseline run_config")
    candidate_config = _mapping(candidate.get("run_config"), "candidate run_config")
    control_fields = ("questions_sha256", "top_k", "cutoffs", "corpus")
    mismatches: dict[str, dict[str, Any]] = {}
    missing_controls: list[str] = []
    for field in control_fields:
        baseline_value = baseline_config.get(field)
        candidate_value = candidate_config.get(field)
        if baseline_value is None or candidate_value is None:
            missing_controls.append(field)
        elif baseline_value != candidate_value:
            mismatches[field] = {"baseline": baseline_value, "candidate": candidate_value}
    if missing_controls:
        raise ValueError(f"paired comparison lacks required frozen controls: {missing_controls}")
    if mismatches:
        raise ValueError(f"paired comparison controls differ: {sorted(mismatches)}")

    baseline_rows = baseline.get("questions", [])
    candidate_rows = candidate.get("questions", [])
    comparisons: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for offset, metric in enumerate(dict.fromkeys(str(value) for value in metrics)):
        try:
            comparisons[metric] = compare_paired_runs(
                baseline_rows,
                candidate_rows,
                metric=metric,
                repetitions=repetitions,
                seed=seed + offset,
            )
        except ValueError as exc:
            if "no paired numeric values" in str(exc):
                unavailable[metric] = str(exc)
                continue
            raise
    corrected = holm_bonferroni(
        {metric: comparison["paired_test"]["p_value"] for metric, comparison in comparisons.items()},
        familywise_alpha=familywise_alpha,
    )
    for metric, correction in corrected.items():
        comparisons[metric]["multiplicity_correction"] = correction

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "contrast": "candidate_minus_baseline",
        "baseline_mode": baseline_config.get("mode"),
        "candidate_mode": candidate_config.get("mode"),
        "shared_controls": {field: baseline_config[field] for field in control_fields},
        "statistics_config": {
            "bootstrap_repetitions": repetitions,
            "base_seed": seed,
            "paired_test": "two-sided paired randomization on query-level differences",
            "multiplicity_correction": "Holm-Bonferroni",
            "familywise_alpha": familywise_alpha,
        },
        "comparisons": comparisons,
        "unavailable_metrics": unavailable,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paired query-level comparisons for two retrieval result files.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_COMPARISON_METRICS))
    parser.add_argument("--bootstrap-repetitions", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--familywise-alpha", type=float, default=0.05)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        baseline = load_result(args.baseline)
        candidate = load_result(args.candidate)
        result = compare_retrieval_results(
            baseline,
            candidate,
            metrics=args.metrics,
            repetitions=args.bootstrap_repetitions,
            seed=args.seed,
            familywise_alpha=args.familywise_alpha,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error={exc}")
        raise SystemExit(1) from exc
    result["input_files"] = {
        "baseline": {"path": str(args.baseline.resolve()), "sha256": _sha256(args.baseline)},
        "candidate": {"path": str(args.candidate.resolve()), "sha256": _sha256(args.candidate)},
    }
    write_results(result, args.out)
    print(f"comparisons={len(result['comparisons'])} out={args.out}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
