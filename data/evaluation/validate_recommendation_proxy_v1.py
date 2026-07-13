from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
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
    expected_reviews_per_pass = len(profiles) * aggregate["execution"]["top_k"] * 2
    if len(pass_one) != expected_reviews_per_pass or len(pass_two) != expected_reviews_per_pass:
        raise ValueError("review pass does not cover every baseline and full-finder ranked item")
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
