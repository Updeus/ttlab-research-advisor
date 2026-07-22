from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = PROJECT_ROOT / "data/evaluation/recommendation_profiles_v1.jsonl"
DEFAULT_PROFILE_SCHEMA = PROJECT_ROOT / "data/evaluation/recommendation_profiles_v1.schema.json"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts/phase4/recommendation_proxy_v1"

FULL_CRITERIA = {
    "paper_relevance",
    "source_fidelity",
    "fact_future_gap_suggestion_separation",
    "novelty_caution",
    "skills_time_data_feasibility",
    "mvp_scope",
    "stretch_goal_appropriateness",
    "risk_calibration",
    "required_skills",
    "evaluation_plan_quality",
    "usefulness_as_ai_proxy",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


ARM_PATHS = {
    "evidence_only": ("baseline", "papers"),
    "full_finder": ("full_finder", "recommendations"),
}
RELEVANCE_VALUES = {"pass": 1.0, "partial": 0.5, "fail": 0.0}


def review_identity(row: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(row["profile_id"]),
        str(row["arm"]),
        int(row["rank"]),
        str(row["paper_id"]),
    )


def format_identity(identity: tuple[str, str, int, str]) -> str:
    profile_id, arm, rank, paper_id = identity
    return f"{profile_id}:{arm}:{rank}:{paper_id}"


def derive_expected_reviews_and_coverage(
    profiles: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    *,
    top_k: int,
) -> tuple[list[tuple[str, str, int, str]], dict[str, dict[str, Any]]]:
    profile_ids = [str(profile["profile_id"]) for profile in profiles]
    output_ids = [str(output["profile_id"]) for output in outputs]
    if Counter(output_ids) != Counter(profile_ids):
        missing = sorted((Counter(profile_ids) - Counter(output_ids)).elements())
        extra = sorted((Counter(output_ids) - Counter(profile_ids)).elements())
        raise ValueError(f"raw outputs do not exactly cover profiles; missing={missing} extra={extra}")
    outputs_by_profile = {str(output["profile_id"]): output for output in outputs}
    expected: list[tuple[str, str, int, str]] = []
    coverage: dict[str, dict[str, Any]] = {}
    expected_slots = len(profiles) * top_k
    for arm, (container_key, items_key) in ARM_PATHS.items():
        returned = 0
        shortfall_slot_ids: list[str] = []
        profiles_at_cutoff = 0
        for profile_id in profile_ids:
            items = list(outputs_by_profile[profile_id].get(container_key, {}).get(items_key, []))
            ranks = [int(item["rank"]) for item in items]
            if len(items) > top_k:
                raise ValueError(f"{profile_id} {arm} returned more than top_k items")
            if ranks != list(range(1, len(items) + 1)):
                raise ValueError(f"{profile_id} {arm} ranks are not contiguous from one")
            paper_ids = [str(item.get("paper_id") or "") for item in items]
            if any(not paper_id for paper_id in paper_ids) or len(paper_ids) != len(set(paper_ids)):
                raise ValueError(f"{profile_id} {arm} contains blank or duplicate paper identities")
            returned += len(items)
            profiles_at_cutoff += int(len(items) == top_k)
            expected.extend((profile_id, arm, int(item["rank"]), str(item["paper_id"])) for item in items)
            shortfall_slot_ids.extend(
                f"{profile_id}:{arm}:{rank}"
                for rank in range(len(items) + 1, top_k + 1)
            )
        coverage[arm] = {
            "returned_items": returned,
            "expected_slots": expected_slots,
            "missing_slots": expected_slots - returned,
            "profiles_at_cutoff": profiles_at_cutoff,
            "shortfall_slot_ids": shortfall_slot_ids,
        }
    return expected, coverage


def validate_review_pass_coverage(
    rows: list[dict[str, Any]],
    expected: list[tuple[str, str, int, str]],
    *,
    pass_number: int,
) -> None:
    expected_counter = Counter(expected)
    actual_counter = Counter(review_identity(row) for row in rows)
    if actual_counter != expected_counter:
        missing = sorted(format_identity(identity) for identity in (expected_counter - actual_counter).elements())
        extra = sorted(format_identity(identity) for identity in (actual_counter - expected_counter).elements())
        raise ValueError(
            f"review pass {pass_number} does not exactly cover emitted ranked items; "
            f"missing={missing} extra={extra}"
        )
    for row in rows:
        if int(row.get("review_pass", 0)) != pass_number:
            raise ValueError(f"review pass {pass_number} contains a mislabeled review_pass value")
        expected_review_id = (
            f"proxy-v1-pass{pass_number}-{row['profile_id']}-{row['arm']}-{int(row['rank'])}"
        )
        if row.get("review_id") != expected_review_id:
            raise ValueError(
                f"review identity mismatch: {row.get('review_id')!r} != {expected_review_id!r}"
            )


def cutoff_normalized_relevance(
    rows: list[dict[str, Any]],
    profile_ids: list[str],
    *,
    arm: str,
    top_k: int,
) -> float:
    scores = {profile_id: 0.0 for profile_id in profile_ids}
    for row in rows:
        if row["arm"] != arm:
            continue
        status = str(row["judgments"]["paper_relevance"]["judgment"])
        if status not in RELEVANCE_VALUES:
            raise ValueError(f"unexpected paper_relevance judgment {status!r}")
        scores[str(row["profile_id"])] += RELEVANCE_VALUES[status]
    return fmean(score / top_k for score in scores.values())


def validate_coverage_metrics(
    aggregate: dict[str, Any],
    profiles: list[dict[str, Any]],
    pass_one: list[dict[str, Any]],
    derived: dict[str, dict[str, Any]],
    *,
    top_k: int,
) -> None:
    metrics = aggregate.get("metrics") or {}
    recorded = metrics.get("ranking_coverage")
    if not isinstance(recorded, dict):
        raise ValueError("aggregate is missing explicit ranking_coverage evidence")
    if recorded.get("requested_cutoff") != top_k:
        raise ValueError("ranking coverage cutoff does not match execution top_k")
    if recorded.get("missing_slots_are_not_imputed") is not True:
        raise ValueError("ranking coverage must state that missing slots were not imputed")
    for arm, expected in derived.items():
        observed = (recorded.get("arms") or {}).get(arm) or {}
        for field in ("returned_items", "expected_slots", "missing_slots", "profiles_at_cutoff"):
            if observed.get(field) != expected[field]:
                raise ValueError(f"ranking coverage mismatch for {arm}.{field}")
        observed_slot_ids = [str(item.get("slot_id")) for item in observed.get("shortfall_slots", [])]
        if observed_slot_ids != expected["shortfall_slot_ids"]:
            raise ValueError(f"ranking coverage shortfall identities do not match {arm} outputs")

    comparison = metrics.get("arm_comparison") or {}
    profile_ids = [str(profile["profile_id"]) for profile in profiles]
    expected_baseline = cutoff_normalized_relevance(
        pass_one, profile_ids, arm="evidence_only", top_k=top_k
    )
    expected_full = cutoff_normalized_relevance(
        pass_one, profile_ids, arm="full_finder", top_k=top_k
    )
    if comparison.get("missing_ranked_slots_scored_as_zero") is not True:
        raise ValueError("arm relevance comparison does not score missing cutoff slots as zero")
    if comparison.get("expected_ranked_slots_per_arm") != len(profiles) * top_k:
        raise ValueError("arm relevance comparison has the wrong cutoff denominator")
    for field, expected in (
        ("baseline_mean_relevance_score", expected_baseline),
        ("full_finder_mean_relevance_score", expected_full),
    ):
        observed = comparison.get(field)
        if not isinstance(observed, (int, float)) or not math.isclose(float(observed), expected, abs_tol=1e-12):
            raise ValueError(f"cutoff-normalized relevance mismatch for {field}: {observed} != {expected}")


def validate(profiles_path: Path, schema_path: Path, artifact_dir: Path) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    profiles = load_jsonl(profiles_path)
    if not 20 <= len(profiles) <= 30:
        raise ValueError(f"expected 20-30 profiles, found {len(profiles)}")
    for index, profile in enumerate(profiles, start=1):
        errors = list(validator.iter_errors(profile))
        if errors:
            raise ValueError(f"profile {index} failed schema validation: {errors[0].message}")

    aggregate = json.loads((artifact_dir / "aggregate_results.json").read_text(encoding="utf-8"))
    failures = json.loads((artifact_dir / "failures.json").read_text(encoding="utf-8"))
    outputs = load_jsonl(artifact_dir / "raw_outputs.jsonl")
    pass_one = load_jsonl(artifact_dir / "review_pass_1.jsonl")
    pass_two = load_jsonl(artifact_dir / "review_pass_2.jsonl")
    sensitivity = json.loads((artifact_dir / "weight_sensitivity.json").read_text(encoding="utf-8"))
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))

    if aggregate["status"] != "complete" or failures:
        raise ValueError("evaluation is not complete or has execution failures")
    if aggregate["execution"]["profiles_completed"] != len(profiles) or len(outputs) != len(profiles):
        raise ValueError("profile/output counts do not match")
    if aggregate["execution"]["persistence"] is not False:
        raise ValueError("evaluation must be transient")
    if aggregate["corpus"]["eligible_chunk_count"] != 719 or aggregate["corpus"]["eligible_paper_count"] != 96:
        raise ValueError("evaluation does not identify the frozen 719-chunk/96-paper corpus")
    if aggregate["corpus"]["topic_author_link_rows_used"] is not False:
        raise ValueError("recommendation evaluation must not rely on topic/author link rows")
    top_k = int(aggregate["execution"]["top_k"])
    expected_reviews, derived_coverage = derive_expected_reviews_and_coverage(
        profiles,
        outputs,
        top_k=top_k,
    )
    validate_review_pass_coverage(pass_one, expected_reviews, pass_number=1)
    validate_review_pass_coverage(pass_two, expected_reviews, pass_number=2)
    validate_coverage_metrics(
        aggregate,
        profiles,
        pass_one,
        derived_coverage,
        top_k=top_k,
    )
    for review in pass_one + pass_two:
        if review["reviewer_type"] != "ai":
            raise ValueError("proxy judgments must be labeled reviewer_type=ai")
        if review["arm"] == "full_finder" and set(review["judgments"]) != FULL_CRITERIA:
            raise ValueError(f"full review {review['review_id']} does not cover every criterion")
        if not review["source_evidence"]:
            raise ValueError(f"review {review['review_id']} has no cited evidence")

    expected_variants = 1 + len(aggregate["recommendation_weights"]["default"]) * 3
    if len(sensitivity["aggregate"]) != expected_variants:
        raise ValueError("weight sensitivity grid is incomplete")
    if sensitivity["weight_origin"] != "hand_authored_heuristic_not_tuned":
        raise ValueError("weight origin is not labeled honestly")

    for name, expected_hash in manifest["artifact_sha256"].items():
        observed = sha256_file(artifact_dir / name)
        if observed != expected_hash:
            raise ValueError(f"artifact hash mismatch for {name}: {observed} != {expected_hash}")

    return {
        "status": "valid",
        "profiles": len(profiles),
        "raw_outputs": len(outputs),
        "reviews_per_pass": len(pass_one),
        "ranking_coverage": derived_coverage,
        "sensitivity_variants": len(sensitivity["aggregate"]),
        "execution_failures": len(failures),
        "corpus": {
            "eligible_papers": aggregate["corpus"]["eligible_paper_count"],
            "eligible_chunks": aggregate["corpus"]["eligible_chunk_count"],
            "snapshot_hash": aggregate["corpus"]["snapshot_hash"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate recommendation proxy evaluation v1.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--schema", type=Path, default=DEFAULT_PROFILE_SCHEMA)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    args = parser.parse_args()
    print(json.dumps(validate(args.profiles, args.schema, args.artifact_dir), indent=2))


if __name__ == "__main__":
    main()
