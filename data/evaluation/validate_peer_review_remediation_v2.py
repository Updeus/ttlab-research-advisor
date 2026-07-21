#!/usr/bin/env python3
"""Validate prospective inputs and completed remediation-v2 artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_peer_review_remediation_v2 as runner


ABSOLUTE_FILESYSTEM_PATH = re.compile(
    r"(?:file:///(?:home|mnt|tmp|root|Users|workspace|workspaces|Volumes|private/var/folders)/"
    r"|(?<![A-Za-z0-9:])/(?:home|mnt|tmp|root|Users|workspace|workspaces|Volumes|private/var/folders)/"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    r"|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)


def assert_no_absolute_filesystem_path(value: Any, location: str) -> None:
    serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if ABSOLUTE_FILESYSTEM_PATH.search(serialized):
        raise AssertionError(f"{location}: absolute operator/system path leaked")


def assert_ai_silver_boundary(value: Any, location: str = "root") -> None:
    if isinstance(value, dict):
        if value.get("reviewer_type") not in {None, "ai"}:
            raise AssertionError(f"{location}: reviewer_type must remain ai")
        for key in ("human_review", "human_validation", "entailment_verified"):
            if value.get(key) is True:
                raise AssertionError(f"{location}: prohibited {key}=true")
        for key, child in value.items():
            assert_ai_silver_boundary(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_ai_silver_boundary(child, f"{location}[{index}]")


def validate_exact_ids_and_splits(
    rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    id_field: str,
    location: str,
) -> dict[str, Any]:
    """Require each frozen ID exactly once with its preregistered split."""

    expected = {str(row[id_field]): str(row.get("split") or "") for row in expected_rows}
    observed_ids = [str(row.get(id_field) or "") for row in rows]
    if not observed_ids or any(not value for value in observed_ids):
        raise AssertionError(f"{location}: missing {id_field}")
    if len(observed_ids) != len(set(observed_ids)):
        raise AssertionError(f"{location}: duplicate {id_field} values")
    if set(observed_ids) != set(expected):
        raise AssertionError(f"{location}: frozen ID inventory drift")
    mismatched_splits = sorted(
        item_id
        for item_id, row in zip(observed_ids, rows, strict=True)
        if str(row.get("split") or "") != expected[item_id]
    )
    if mismatched_splits:
        raise AssertionError(f"{location}: frozen split drift for {mismatched_splits}")
    return {
        "count": len(rows),
        "unique": True,
        "exact_frozen_ids": True,
        "exact_frozen_splits": True,
    }


def validate_passes(
    first_path: Path,
    second_path: Path,
    id_field: str,
    expected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    first = runner.read_jsonl(first_path)
    second = runner.read_jsonl(second_path)
    validate_exact_ids_and_splits(first, expected_rows, id_field, first_path.name)
    validate_exact_ids_and_splits(second, expected_rows, id_field, second_path.name)
    first_ids = [str(row[id_field]) for row in first]
    second_ids = [str(row[id_field]) for row in second]
    if set(first_ids) != set(second_ids):
        raise AssertionError(f"{first_path.name}/{second_path.name}: pass case sets differ")
    if first_ids == second_ids:
        raise AssertionError(f"{first_path.name}/{second_path.name}: presentation order was not shuffled")
    if any(row.get("review_pass") != "pass_1" for row in first):
        raise AssertionError(f"{first_path.name}: incorrect pass labels")
    if any(row.get("review_pass") != "pass_2" for row in second):
        raise AssertionError(f"{second_path.name}: incorrect pass labels")
    if any((row.get("reviewer") or {}).get("reviewer_id") != "codex-ai-review" for row in first + second):
        raise AssertionError("reviewer identity drift")
    return {"case_count": len(first), "orders_differ": True, "same_case_set": True}


FORBIDDEN_VERSIONABLE_RAW_KEYS = {
    "answer",
    "snippet",
    "text",
    "claim",
    "title",
    "paper_title",
    "authors",
    "paper_focus",
    "extension_title",
    "extension_summary",
    "why_it_fits_student",
    "mvp_scope",
    "stretch_goals",
    "required_skills",
    "skills_gap",
    "data_required",
    "evaluation_plan",
    "related_papers",
    "potential_researcher_fit",
}


def assert_versionable_raw_boundary(value: Any, location: str) -> None:
    if isinstance(value, dict):
        leaked = FORBIDDEN_VERSIONABLE_RAW_KEYS.intersection(value)
        if leaked:
            raise AssertionError(f"{location}: rights-sensitive textual keys leaked: {sorted(leaked)}")
        for key, child in value.items():
            if key.endswith("_attestation") and isinstance(child, dict) and "sha256" in child:
                if not re.fullmatch(r"[0-9a-f]{64}", str(child.get("sha256") or "")):
                    raise AssertionError(f"{location}.{key}: invalid text attestation hash")
                if int(child.get("utf8_bytes", -1)) < 0 or int(child.get("word_count", -1)) < 0:
                    raise AssertionError(f"{location}.{key}: invalid text attestation counts")
            assert_versionable_raw_boundary(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_versionable_raw_boundary(child, f"{location}[{index}]")


def validate_manifest_output_inventory(
    manifest: dict[str, Any],
    *,
    require_attestation: bool,
) -> None:
    expected_paths = {
        runner.relative(path): {
            "sha256": runner.sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for key, path in runner.OUTPUT_PATHS.items()
        if key != "manifest"
    }
    if manifest.get("outputs") != expected_paths:
        raise AssertionError("manifest versionable output inventory/hash/size drift")
    if manifest.get("freeze_receipt") != runner.relative(runner.RECEIPT_PATH):
        raise AssertionError("manifest freeze-receipt locator drift")
    if manifest.get("freeze_receipt_sha256") != runner.sha256_file(runner.RECEIPT_PATH):
        raise AssertionError("manifest freeze-receipt hash drift")
    expected_package_names = {
        runner.RECEIPT_PATH.name,
        *(path.name for path in runner.OUTPUT_PATHS.values()),
    }
    if require_attestation:
        expected_package_names.add(runner.VALIDATION_ATTESTATION_PATH.name)
    observed_package_names = validate_flat_regular_file_inventory(
        runner.OUT_DIR,
        expected_package_names,
        "canonical package",
    )
    if observed_package_names != expected_package_names:
        raise AssertionError(
            "canonical package filename inventory drift: "
            f"missing={sorted(expected_package_names - observed_package_names)}, "
            f"unexpected={sorted(observed_package_names - expected_package_names)}"
        )


def validate_flat_regular_file_inventory(
    directory: Path,
    expected_names: set[str],
    location: str,
) -> set[str]:
    """Reject symlinks and nested/non-file entries in a canonical flat package."""

    if directory.is_symlink() or not directory.is_dir():
        raise AssertionError(f"{location}: expected a real directory, not a symlink")
    observed: set[str] = set()
    for entry in directory.iterdir():
        observed.add(entry.name)
        if entry.is_symlink() or not entry.is_file():
            raise AssertionError(
                f"{location}: non-regular or nested entry is prohibited: {entry.name}"
            )
    if observed != expected_names:
        raise AssertionError(
            f"{location}: flat filename inventory drift: "
            f"missing={sorted(expected_names - observed)}, "
            f"unexpected={sorted(observed - expected_names)}"
        )
    return observed


def validate_restricted_inventory(manifest: dict[str, Any], *, require_files: bool) -> None:
    inventory = manifest.get("restricted_raw_outputs") or {}
    expected_names = set(runner.RESTRICTED_OUTPUT_PATHS)
    if (
        inventory.get("required") is not True
        or inventory.get("retained_locally") is not True
        or inventory.get("committed") is not False
        or inventory.get("release_included") is not False
        or inventory.get("lawful_local_corpus_access_required_for_exact_reproduction") is not True
        or set((inventory.get("files") or {})) != expected_names
    ):
        raise AssertionError("restricted raw-output policy or logical inventory drift")
    for name, metadata in (inventory.get("files") or {}).items():
        path = runner.RESTRICTED_OUTPUT_PATHS[name]
        if metadata.get("filename") != path.name or "/" in str(metadata.get("filename") or ""):
            raise AssertionError(f"restricted output {name} discloses a path or has filename drift")
        if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("sha256") or "")):
            raise AssertionError(f"restricted output {name} lacks a content hash")
        if int(metadata.get("bytes", -1)) <= 0:
            raise AssertionError(f"restricted output {name} has an invalid size")
        if require_files:
            if not path.is_file():
                raise FileNotFoundError(f"required operator-local restricted output is missing: {path.name}")
            if runner.sha256_file(path) != metadata["sha256"] or path.stat().st_size != metadata["bytes"]:
                raise AssertionError(f"restricted output {name} differs from its content-free inventory")


def versionable_validation_report_portion(
    manifest: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Build the content-bound portion independently checkable from a release.

    This deliberately excludes the operator-local raw-output result.  A release
    consumer can verify that a strict validation *recorded* that check, but
    cannot independently repeat it without the restricted files.
    """

    return {
        "schema_version": 1,
        "evaluation_id": "peer-review-remediation-v2",
        "mode": "completed_versionable_package",
        "manifest_sha256": runner.sha256_file(runner.OUTPUT_PATHS["manifest"]),
        "freeze_receipt_sha256": runner.sha256_file(runner.RECEIPT_PATH),
        "versionable_output_inventory_sha256": runner.sha256_bytes(
            runner.canonical_json(manifest.get("outputs") or {}).encode("utf-8")
        ),
        "evaluation_source_commit": manifest.get("evaluation_source_commit"),
        "frozen_dataset_identity_sha256": runner.sha256_bytes(
            runner.canonical_json(receipt.get("frozen_dataset_identity") or {}).encode("utf-8")
        ),
        "locked_validator_identity_sha256": runner.sha256_bytes(
            runner.canonical_json(receipt.get("locked_validator_identity") or {}).encode("utf-8")
        ),
        "package_file_count": 2 + len(runner.OUTPUT_PATHS),
        "rights_sensitive_raw_text_in_versionable_package": False,
        "restricted_raw_validation_scope": (
            "recorded_attestation_from_full_validation_not_independently_rechecked"
        ),
        "checks": [
            "exact_flat_file_inventory",
            "manifest_output_hashes_and_sizes",
            "freeze_receipt_identity",
            "frozen_id_and_split_inventory",
            "versionable_aggregate_recomputation",
            "ai_silver_claim_boundary",
        ],
    }


def validation_report_sha256(
    _report: dict[str, Any] | None = None,
    *,
    manifest: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
) -> str:
    """Hash only the package-derived report portion a consumer can recompute."""

    manifest = manifest or json.loads(
        runner.OUTPUT_PATHS["manifest"].read_text(encoding="utf-8")
    )
    receipt = receipt or json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    portion = versionable_validation_report_portion(manifest, receipt)
    return runner.sha256_bytes(runner.canonical_json(portion).encode("utf-8"))


def write_validation_attestation(report: dict[str, Any]) -> None:
    """Write a post-validation attestation that is outside the manifest cycle."""

    if (
        report.get("status") != "pass"
        or report.get("restricted_raw_files_checked") is not True
        or (report.get("strict_recomputation") or {}).get("status") != "pass"
    ):
        raise AssertionError(
            "validation attestation requires a passing strict restricted-raw recomputation"
        )
    path = runner.VALIDATION_ATTESTATION_PATH
    if path.exists():
        raise FileExistsError(f"validation attestation already exists: {runner.relative(path)}")
    manifest = json.loads(runner.OUTPUT_PATHS["manifest"].read_text(encoding="utf-8"))
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    attestation = {
        "schema_version": 1,
        "evaluation_id": "peer-review-remediation-v2",
        "status": "completed_package_validated",
        "validated_at": runner.utc_now(),
        "evaluation_source_commit": manifest.get("evaluation_source_commit"),
        "manifest_path": runner.relative(runner.OUTPUT_PATHS["manifest"]),
        "manifest_sha256": runner.sha256_file(runner.OUTPUT_PATHS["manifest"]),
        "freeze_receipt_sha256": runner.sha256_file(runner.RECEIPT_PATH),
        "versionable_output_inventory_sha256": runner.sha256_bytes(
            runner.canonical_json(manifest.get("outputs") or {}).encode("utf-8")
        ),
        "validation_report_sha256": validation_report_sha256(
            report,
            manifest=manifest,
            receipt=receipt,
        ),
        "locked_validator_identity": runner.locked_validator_identity(),
        "restricted_raw_files_required_for_this_validation": True,
        "rights_sensitive_raw_text_in_versionable_package": False,
        "claim_boundary": (
            "Strict structural/package validation passed in the frozen locked environment. "
            "This is AI-silver technical evidence, not human, entailment, public, feasibility, or rights approval."
        ),
    }
    runner.write_json(path, attestation)


def validate_validation_attestation(report: dict[str, Any] | None) -> None:
    path = runner.VALIDATION_ATTESTATION_PATH
    if not path.is_file():
        raise FileNotFoundError("completed-package validation attestation is missing")
    attestation = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "evaluation_id",
        "status",
        "validated_at",
        "evaluation_source_commit",
        "manifest_path",
        "manifest_sha256",
        "freeze_receipt_sha256",
        "versionable_output_inventory_sha256",
        "validation_report_sha256",
        "locked_validator_identity",
        "restricted_raw_files_required_for_this_validation",
        "rights_sensitive_raw_text_in_versionable_package",
        "claim_boundary",
    }
    if set(attestation) != expected_keys:
        raise AssertionError("validation attestation schema drift")
    manifest_path = runner.OUTPUT_PATHS["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    if (
        attestation.get("schema_version") != 1
        or attestation.get("evaluation_id") != "peer-review-remediation-v2"
        or attestation.get("status") != "completed_package_validated"
        or attestation.get("manifest_path") != runner.relative(manifest_path)
        or attestation.get("manifest_sha256") != runner.sha256_file(manifest_path)
        or attestation.get("freeze_receipt_sha256") != runner.sha256_file(runner.RECEIPT_PATH)
        or attestation.get("evaluation_source_commit") != manifest.get("evaluation_source_commit")
        or attestation.get("locked_validator_identity") != runner.locked_validator_identity()
        or attestation.get("restricted_raw_files_required_for_this_validation") is not True
        or attestation.get("rights_sensitive_raw_text_in_versionable_package") is not False
    ):
        raise AssertionError("validation attestation identity or boundary drift")
    expected_inventory_hash = runner.sha256_bytes(
        runner.canonical_json(manifest.get("outputs") or {}).encode("utf-8")
    )
    if attestation.get("versionable_output_inventory_sha256") != expected_inventory_hash:
        raise AssertionError("validation attestation output-inventory drift")
    recorded_report_hash = str(attestation.get("validation_report_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_report_hash):
        raise AssertionError("validation attestation report digest is invalid")
    expected_report_hash = validation_report_sha256(
        report,
        manifest=manifest,
        receipt=receipt,
    )
    if recorded_report_hash != expected_report_hash:
        raise AssertionError("validation attestation package-bound report digest drift")


QA_REVIEW_FIELDS = [
    "actual_answered",
    "correct_selective_decision",
    "citation_links",
    "answer_points",
    "claim_count",
    "structurally_cited_claim_count",
    "returned_citation_count",
    "used_returned_citation_count",
]
FINDER_REVIEW_FIELDS = [
    "evidence_only_gold_rank",
    "full_finder_gold_rank",
    "candidate_checks",
    "candidate_specific_template_conformance_pass",
    "source_fact_suggestion_separation_pass",
    "unknown_implementation_time_retained",
    "full_profile_constraint_contract_fidelity",
]


def _assert_exact(actual: Any, expected: Any, location: str) -> None:
    if actual != expected:
        raise AssertionError(f"{location}: deterministic recomputation drift")


def _source_hashes_from_versionable_rows(
    rows: list[dict[str, Any]],
    location: str,
) -> dict[str, dict[str, str]]:
    """Recover content hashes carried by the structural versionable projection."""

    source_hashes: dict[str, dict[str, str]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            chunk_id = str(value.get("chunk_id") or "")
            chunk_hash = value.get("chunk_text_sha256")
            effective_hash = value.get("effective_source_sha256")
            if chunk_id and chunk_hash is not None and effective_hash is not None:
                hashes = {
                    "chunk_text_sha256": str(chunk_hash),
                    "effective_source_sha256": str(effective_hash),
                }
                if any(
                    not re.fullmatch(r"[0-9a-f]{64}", candidate)
                    for candidate in hashes.values()
                ):
                    raise AssertionError(f"{location}: invalid source hash for {chunk_id}")
                previous = source_hashes.get(chunk_id)
                if previous is not None and previous != hashes:
                    raise AssertionError(f"{location}: conflicting source hashes for {chunk_id}")
                source_hashes[chunk_id] = hashes
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(rows)
    return source_hashes


def _source_hashes_from_frozen_database(
    chunk_ids: set[str],
    location: str,
) -> dict[str, dict[str, str]]:
    """Recompute retrieval-source identities from the receipt-bound SQLite data."""

    if not chunk_ids:
        return {}
    connection = sqlite3.connect(f"file:{runner.DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        source_hashes: dict[str, dict[str, str]] = {}
        for chunk_id in sorted(chunk_ids):
            row = connection.execute(
                "SELECT c.chunk_id, c.paper_id, c.chunk_index, c.page_start, c.page_end, "
                "c.section, c.text, c.source_hash, p.title, p.authors, p.year, p.venue, "
                "p.topics, p.corpus_eligibility_status "
                "FROM chunk c LEFT JOIN paper p ON p.paper_id = c.paper_id "
                "WHERE c.chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                raise AssertionError(f"{location}: frozen database lacks chunk {chunk_id}")
            (
                observed_chunk_id,
                paper_id,
                chunk_index,
                page_start,
                page_end,
                section,
                text,
                persisted_source_hash,
                title,
                authors_raw,
                year,
                venue,
                topics_raw,
                eligibility,
            ) = row

            def decode_list(raw: Any) -> list[Any]:
                if raw in {None, ""}:
                    return []
                try:
                    decoded = json.loads(str(raw))
                except json.JSONDecodeError as exc:
                    raise AssertionError(
                        f"{location}: malformed frozen list metadata for {chunk_id}"
                    ) from exc
                if not isinstance(decoded, list):
                    raise AssertionError(
                        f"{location}: frozen list metadata is not a list for {chunk_id}"
                    )
                return decoded

            chunk_text_hash = runner.sha256_bytes(str(text or "").encode("utf-8"))
            if persisted_source_hash != chunk_text_hash:
                raise AssertionError(
                    f"{location}: persisted source hash disagrees with frozen text for {chunk_id}"
                )
            effective_identity = {
                "chunk": {
                    "chunk_id": observed_chunk_id,
                    "paper_id": paper_id,
                    "chunk_index": chunk_index,
                    "page_start": page_start,
                    "page_end": page_end,
                    "section": section,
                    "text": text,
                },
                "paper": {
                    "title": title,
                    "authors": decode_list(authors_raw),
                    "year": year,
                    "venue": venue,
                    "topics": decode_list(topics_raw),
                    "corpus_eligibility_status": eligibility,
                },
                "identity_contract": "retrieval_source_identity_v2",
            }
            source_hashes[chunk_id] = {
                "chunk_text_sha256": chunk_text_hash,
                "effective_source_sha256": runner.sha256_bytes(
                    runner.canonical_json(effective_identity).encode("utf-8")
                ),
            }
        return source_hashes
    finally:
        connection.close()


def _finder_constraint_variation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("constraint_pair"):
            pairs.setdefault(str(row["constraint_pair"]), []).append(row)
    return {
        name: {
            "profile_ids": sorted(row["profile_id"] for row in pair_rows),
            "input_available_times": sorted(
                {row["input_available_time"] for row in pair_rows}
            ),
            "input_preferred_difficulties": sorted(
                {row["input_preferred_difficulty"] for row in pair_rows}
            ),
            "evidence_only_rankings": {
                row["profile_id"]: row["evidence_only_ranked_paper_ids"]
                for row in pair_rows
            },
            "full_finder_rankings": {
                row["profile_id"]: row["full_finder_ranked_paper_ids"]
                for row in pair_rows
            },
            "full_ranking_changed_across_constraints": len(
                {tuple(row["full_finder_ranked_paper_ids"]) for row in pair_rows}
            )
            > 1,
            "all_profiles_satisfy_full_constraint_contract": all(
                row["full_profile_constraint_contract_fidelity"] for row in pair_rows
            ),
            "all_implementation_times_remain_unknown": all(
                row["unknown_implementation_time_retained"] for row in pair_rows
            ),
            "interpretation": (
                "The system preserves supplied constraints but does not convert available "
                "time into a paper-supported feasibility fact."
            ),
        }
        for name, pair_rows in pairs.items()
    }


def validate_strict_recomputation(
    decoded: dict[str, Any],
    restricted: dict[str, list[dict[str, Any]]],
    *,
    qa_cases: list[dict[str, Any]],
    finder_cases: list[dict[str, Any]],
    topic_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute all deterministic v2 judgments from cases and restricted raw data."""

    for name, rows in restricted.items():
        assert_ai_silver_boundary(rows, f"restricted.{name}")

    qa_case_by_id = {str(case["case_id"]): case for case in qa_cases}
    qa_versionable_by_id = {str(row["case_id"]): row for row in decoded["qa_raw"]}
    qa_structural_hashes = _source_hashes_from_versionable_rows(
        decoded["qa_raw"], "qa_raw"
    )
    qa_hashes = _source_hashes_from_frozen_database(
        set(qa_structural_hashes), "qa_raw"
    )
    _assert_exact(qa_structural_hashes, qa_hashes, "QA frozen source identities")
    qa_review_outputs: list[dict[str, Any]] = []
    for row in restricted["qa_full_raw"]:
        case_id = str(row["case_id"])
        case = qa_case_by_id[case_id]
        _assert_exact(
            row.get("case"),
            runner.redact_json_strings(case),
            f"qa restricted frozen case {case_id}",
        )
        review_output = runner.sanitize_qa_response(case, row.get("response") or {}, qa_hashes)
        _assert_exact(
            runner.versionable_qa_output(review_output),
            qa_versionable_by_id[case_id],
            f"qa versionable projection {case_id}",
        )
        qa_review_outputs.append(review_output)
    qa_outputs_by_id = {str(row["case_id"]): row for row in qa_review_outputs}
    qa_pass1 = runner.shuffled_review(
        qa_cases, qa_outputs_by_id, "pass_1", runner.review_qa_case
    )
    qa_pass2 = runner.shuffled_review(
        qa_cases, qa_outputs_by_id, "pass_2", runner.review_qa_case
    )
    _assert_exact(decoded["qa_pass1"], qa_pass1, "QA pass 1")
    _assert_exact(decoded["qa_pass2"], qa_pass2, "QA pass 2")
    qa_disagreements = runner.review_disagreements(
        qa_pass1, qa_pass2, QA_REVIEW_FIELDS
    )
    _assert_exact(decoded["qa_disagreements"], qa_disagreements, "QA disagreements")
    qa_by_split = {
        split: runner.aggregate_qa([row for row in qa_pass1 if row["split"] == split])
        for split in ("dev", "test")
    }
    qa_by_split["all"] = runner.aggregate_qa(qa_pass1)
    _assert_exact(decoded["qa_metrics"].get("by_split"), qa_by_split, "QA aggregates")
    _assert_exact(
        decoded["qa_metrics"].get("repeatability"),
        qa_disagreements,
        "QA repeatability",
    )
    qa_bootstrap = runner.bootstrap_metrics(
        [row for row in qa_pass1 if row["split"] == "test"],
        runner.aggregate_qa,
        cluster_key="cluster_id",
        unit="named_source_paper",
    )
    _assert_exact(
        decoded["qa_metrics"].get("test_bootstrap_95_ci"),
        qa_bootstrap,
        "QA seeded bootstrap",
    )

    finder_case_by_id = {str(case["profile_id"]): case for case in finder_cases}
    finder_versionable_by_id = {
        str(row["profile_id"]): row for row in decoded["finder_raw"]
    }
    finder_structural_hashes = _source_hashes_from_versionable_rows(
        decoded["finder_raw"], "finder_raw"
    )
    finder_hashes = _source_hashes_from_frozen_database(
        set(finder_structural_hashes), "finder_raw"
    )
    _assert_exact(
        finder_structural_hashes,
        finder_hashes,
        "Finder frozen source identities",
    )
    finder_review_outputs: list[dict[str, Any]] = []
    for row in restricted["finder_full_raw"]:
        profile_id = str(row["profile_id"])
        case = finder_case_by_id[profile_id]
        _assert_exact(
            row.get("case"),
            runner.redact_json_strings(case),
            f"Finder restricted frozen case {profile_id}",
        )
        review_output = runner.sanitize_finder(
            case,
            row.get("retrieval") or {},
            row.get("evidence_only") or {},
            row.get("full_finder") or {},
            finder_hashes,
        )
        _assert_exact(
            runner.versionable_finder_output(review_output),
            finder_versionable_by_id[profile_id],
            f"Finder versionable projection {profile_id}",
        )
        finder_review_outputs.append(review_output)
    finder_outputs_by_id = {
        str(row["profile_id"]): row for row in finder_review_outputs
    }
    finder_pass1 = runner.shuffled_review(
        finder_cases, finder_outputs_by_id, "pass_1", runner.review_finder_case
    )
    finder_pass2 = runner.shuffled_review(
        finder_cases, finder_outputs_by_id, "pass_2", runner.review_finder_case
    )
    _assert_exact(decoded["finder_pass1"], finder_pass1, "Finder pass 1")
    _assert_exact(decoded["finder_pass2"], finder_pass2, "Finder pass 2")
    finder_disagreements = runner.review_disagreements(
        finder_pass1, finder_pass2, FINDER_REVIEW_FIELDS
    )
    _assert_exact(
        decoded["finder_disagreements"],
        finder_disagreements,
        "Finder disagreements",
    )
    finder_by_split = {
        split: runner.aggregate_finder(
            [row for row in finder_pass1 if row["split"] == split]
        )
        for split in ("dev", "test", "sensitivity")
    }
    finder_by_split["primary_dev_and_test"] = runner.aggregate_finder(
        [row for row in finder_pass1 if row["split"] in {"dev", "test"}]
    )
    finder_by_split["all_including_sensitivity"] = runner.aggregate_finder(
        finder_pass1
    )
    _assert_exact(
        decoded["finder_metrics"].get("by_split"),
        finder_by_split,
        "Finder aggregates",
    )
    _assert_exact(
        decoded["finder_metrics"].get("repeatability"),
        finder_disagreements,
        "Finder repeatability",
    )
    _assert_exact(
        decoded["finder_metrics"].get("constraint_variation"),
        _finder_constraint_variation(finder_pass1),
        "Finder constraint variation",
    )
    finder_bootstrap = runner.bootstrap_metrics(
        [row for row in finder_pass1 if row["split"] == "test"],
        runner.aggregate_finder,
        cluster_key="cluster_id",
        unit="profile_family",
    )
    _assert_exact(
        decoded["finder_metrics"].get("test_bootstrap_95_ci"),
        finder_bootstrap,
        "Finder seeded bootstrap",
    )

    topic_case_by_id = {str(case["case_id"]): case for case in topic_cases}
    topic_versionable_by_id = {
        str(row["case_id"]): row for row in decoded["topic_predictions"]
    }
    topic_structural_hashes = _source_hashes_from_versionable_rows(
        decoded["topic_predictions"], "topic_predictions"
    )
    topic_hashes = _source_hashes_from_frozen_database(
        set(topic_structural_hashes), "topic_predictions"
    )
    _assert_exact(
        topic_structural_hashes,
        topic_hashes,
        "topic frozen source identities",
    )
    topic_outputs: list[dict[str, Any]] = []
    for row in restricted["topic_full_raw"]:
        case_id = str(row["case_id"])
        if case_id not in topic_case_by_id:
            raise AssertionError(f"topic restricted output has unknown case: {case_id}")
        output = {key: value for key, value in row.items() if key != "restriction"}
        _assert_exact(
            runner.versionable_topic_output(output),
            topic_versionable_by_id[case_id],
            f"topic versionable projection {case_id}",
        )
        topic_outputs.append(output)
    vocabulary = list(decoded["topic_metrics"].get("controlled_vocabulary") or [])
    topic_by_split = {
        split: runner.topic_aggregate(
            [row for row in topic_outputs if row["split"] == split], vocabulary
        )
        for split in ("dev", "test")
    }
    topic_by_split["all"] = runner.topic_aggregate(topic_outputs, vocabulary)
    _assert_exact(
        decoded["topic_metrics"].get("by_split"), topic_by_split, "topic aggregates"
    )
    topic_bootstrap = runner.bootstrap_metrics(
        [row for row in topic_outputs if row["split"] == "test"],
        lambda sampled: runner.topic_bootstrap_aggregate(sampled, vocabulary),
        cluster_key="cluster_id",
        unit="paper",
    )
    _assert_exact(
        decoded["topic_metrics"].get("test_bootstrap_95_ci"),
        topic_bootstrap,
        "topic seeded bootstrap",
    )

    return {
        "restricted_versionable_projections_exact": True,
        "qa_passes_disagreements_aggregates_bootstrap_exact": True,
        "finder_passes_disagreements_aggregates_bootstrap_exact": True,
        "topic_aggregates_bootstrap_exact": True,
        "reviewer_boundary": (
            "two shuffled passes of one deterministic AI-silver procedure; "
            "not independent or human review"
        ),
    }


def validate_static(*, require_database_locators: bool = True) -> dict[str, Any]:
    frozen = runner.validate_static_protocol()
    if require_database_locators:
        runner.validate_sqlite_source_locators()
    protocol = json.loads(runner.PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert_ai_silver_boundary(protocol, "protocol")
    assert_no_absolute_filesystem_path(protocol, "protocol")
    for label, path in (
        ("ask_cases", runner.QA_PATH),
        ("finder_cases", runner.FINDER_PATH),
        ("topic_cases", runner.TOPIC_PATH),
    ):
        assert_no_absolute_filesystem_path(runner.read_jsonl(path), label)
    if protocol["ask"]["retrieval_scope"] != "technical":
        raise AssertionError("Ask protocol must explicitly use technical scope")
    if protocol["finder"]["retrieval_scope"] != "technical":
        raise AssertionError("Finder protocol must explicitly use technical scope")
    boundary = protocol.get("corpus_and_projection_boundary") or {}
    if boundary.get("technical_selection_predicate") != runner.TECHNICAL_SELECTION_PREDICATE:
        raise AssertionError("technical corpus predicate drift")
    if boundary.get("public_projection_evaluated") is not False:
        raise AssertionError("public projection must remain outside v2")
    if boundary.get("public_projection_predicate_recorded_not_tested") != runner.PUBLIC_SELECTION_PREDICATE:
        raise AssertionError("recorded public projection predicate drift")
    generation_link = boundary.get("generation_link_reconciliation") or {}
    if generation_link.get("required_before_index_rebuild") is not True:
        raise AssertionError("generation-link reconciliation is not required before indexing")
    if generation_link.get("legacy_or_mismatched_artifacts") != "quarantine_fail_closed":
        raise AssertionError("legacy generation artifacts are not quarantined fail-closed")
    if generation_link.get("zero_generation_linked_corpus_permitted") is not False:
        raise AssertionError("protocol permits an empty generation-linked technical corpus")
    provider_environment = protocol["ask"].get("provider_environment") or {}
    if provider_environment != {
        "allowed_llm_providers": ["offline_extractive"],
        "default_llm_provider": "offline_extractive",
        "external_provider_invoked": False,
    }:
        raise AssertionError("offline Ask provider environment is not fully pinned")
    index_preparation = protocol["ask"].get("temporary_index_preparation") or {}
    if index_preparation.get("rebuild_keyword_index") is not True:
        raise AssertionError("temporary keyword-index rebuild is not required")
    if index_preparation.get("live_database_mutated") is not False:
        raise AssertionError("protocol permits a tracked database index mutation")
    if protocol["ocr"].get("execution_path") != (
        "backend.app.ingestion.pdf_parser.extract_pdf_text with run_ocr=true and a TesseractOCRProvider"
    ):
        raise AssertionError("OCR protocol does not exercise the full parser pipeline")
    ocr_gold = json.loads(runner.OCR_GOLD_PATH.read_text(encoding="utf-8"))
    generation = ocr_gold.get("generation") or {}
    if generation.get("font_id") != runner.OCR_FIXTURE_FONT_ID:
        raise AssertionError("OCR fixture logical font identity drift")
    if generation.get("font_sha256") != runner.sha256_file(runner.OCR_FIXTURE_FONT_PATH):
        raise AssertionError("OCR fixture font hash differs from the logical runtime font")
    if "font_path" in generation:
        raise AssertionError("OCR fixture records an absolute font path instead of a logical identity")
    assert_no_absolute_filesystem_path(ocr_gold, "ocr_gold")
    backend_python_paths = set((runner.ROOT / "backend" / "app").rglob("*.py"))
    if not backend_python_paths.issubset(set(runner.CODE_PATHS)):
        raise AssertionError("code freeze does not inventory every backend/app Python file")
    if protocol["historical_v1"]["immutable"] is not True:
        raise AssertionError("v1 evidence must remain immutable")
    if protocol["historical_v1"]["classification"] != "historical_post_selection_descriptive":
        raise AssertionError("v1 ablations are not prospective validation")
    output_contract = protocol.get("output_contract") or {}
    if output_contract.get("manuscript_macros") != "manuscript_macros_v2.tex":
        raise AssertionError("v2 manuscript macro output is not preregistered")
    if output_contract.get("validation_attestation") != runner.VALIDATION_ATTESTATION_PATH.name:
        raise AssertionError("v2 validation attestation is not preregistered")
    if output_contract.get("release_filename_policy") != "exact_allowlist_only":
        raise AssertionError("v2 exact release allowlist is not preregistered")
    if output_contract.get("hand_entered_manuscript_metrics_permitted") is not False:
        raise AssertionError("v2 permits hand-entered manuscript metrics")
    restricted = output_contract.get("restricted_raw_output_policy") or {}
    if (
        restricted.get("required") is not True
        or restricted.get("commit_or_release_permitted") is not False
        or restricted.get("manifest_records_sha256_and_size") is not True
        or restricted.get("lawful_local_corpus_access_required_for_reproduction") is not True
    ):
        raise AssertionError("restricted raw-output publication boundary drift")
    if (protocol.get("bootstrap") or {}).get("method") != "cluster_level_percentile_bootstrap":
        raise AssertionError("v2 does not preregister cluster-level bootstrap intervals")
    qa_cases = runner.read_jsonl(runner.QA_PATH)
    negative_cases = [row for row in qa_cases if not row.get("expected_answerable")]
    if len(negative_cases) != 6 or any(
        (row.get("construction") or {}).get("method") != "source_derived_in_domain_absence_probe"
        for row in negative_cases
    ):
        raise AssertionError("Ask negatives are not six source-derived in-domain absence probes")
    finder_cases = runner.read_jsonl(runner.FINDER_PATH)
    sensitivity_ids = [row["profile_id"] for row in finder_cases if row.get("split") == "sensitivity"]
    if sensitivity_ids != protocol["finder"].get("frozen_sensitivity_ids"):
        raise AssertionError("Finder sensitivity split drift")
    return {
        "status": "pass",
        "frozen_ids": frozen,
        "sqlite_source_locators_checked": require_database_locators,
    }


def validate_versionable_package() -> dict[str, Any]:
    """Validate the distributable package without requiring the local corpus.

    The post-validation attestation records that the stricter local validator
    checked the restricted raw inventory; without those local files this mode
    cannot independently prove or repeat that check. This pass independently
    checks every versionable filename, hash, boundary, frozen ID/split, and
    aggregate.
    """

    static = validate_static(require_database_locators=False)
    if not runner.RECEIPT_PATH.is_file() or not runner.OUTPUT_PATHS["manifest"].is_file():
        raise FileNotFoundError("completed v2 receipt or manifest is missing")
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(runner.OUTPUT_PATHS["manifest"].read_text(encoding="utf-8"))
    validate_manifest_output_inventory(manifest, require_attestation=True)
    validate_restricted_inventory(manifest, require_files=False)
    evaluation_source_commit = str(receipt.get("evaluation_source_commit") or "")
    code_commit = (
        (manifest.get("runtime_provenance_validation") or {}).get("code_identity") or {}
    ).get("git_commit")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", evaluation_source_commit)
        or evaluation_source_commit != (receipt.get("git") or {}).get("head")
        or evaluation_source_commit != manifest.get("evaluation_source_commit")
        or evaluation_source_commit != code_commit
    ):
        raise AssertionError("versionable package commit identities disagree")
    if receipt.get("frozen_dataset_identity") != runner.frozen_dataset_identity():
        raise AssertionError("versionable package frozen dataset identity drift")
    if manifest.get("frozen_dataset_identity") != receipt.get("frozen_dataset_identity"):
        raise AssertionError("versionable manifest/receipt dataset identities disagree")
    if (
        receipt.get("locked_validator_identity") != runner.locked_validator_identity()
        or manifest.get("locked_validator_identity") != receipt.get("locked_validator_identity")
    ):
        raise AssertionError("versionable package validator/environment identity drift")
    required_false = (
        "public_validation_claimed",
        "public_projection_exercised",
        "entailment_claimed",
        "human_validation_claimed",
        "v1_artifacts_overwritten",
        "tracked_database_mutated",
        "release_contains_rights_sensitive_raw_text",
    )
    if any(manifest.get(field) is not False for field in required_false):
        raise AssertionError("versionable package claim boundary drift")
    if (
        manifest.get("evaluation_id") != "peer-review-remediation-v2"
        or manifest.get("status") != "completed"
        or manifest.get("technical_scope_only") is not True
        or manifest.get("technical_selection_predicate") != runner.TECHNICAL_SELECTION_PREDICATE
        or manifest.get("public_selection_predicate_recorded_not_tested")
        != runner.PUBLIC_SELECTION_PREDICATE
    ):
        raise AssertionError("versionable package identity/scope drift")

    decoded: dict[str, Any] = {}
    for name, path in runner.OUTPUT_PATHS.items():
        if path.suffix == ".jsonl":
            decoded[name] = runner.read_jsonl(path)
        elif path.suffix == ".tex":
            decoded[name] = path.read_text(encoding="utf-8")
        else:
            decoded[name] = json.loads(path.read_text(encoding="utf-8"))
        assert_ai_silver_boundary(decoded[name], f"versionable.{name}")
        assert_no_absolute_filesystem_path(decoded[name], f"versionable.{name}")
    assert_no_absolute_filesystem_path(receipt, "versionable.freeze_receipt")

    qa_cases = runner.read_jsonl(runner.QA_PATH)
    finder_cases = runner.read_jsonl(runner.FINDER_PATH)
    topic_cases = runner.read_jsonl(runner.TOPIC_PATH)
    qa_passes = validate_passes(
        runner.OUTPUT_PATHS["qa_pass1"],
        runner.OUTPUT_PATHS["qa_pass2"],
        "case_id",
        qa_cases,
    )
    finder_passes = validate_passes(
        runner.OUTPUT_PATHS["finder_pass1"],
        runner.OUTPUT_PATHS["finder_pass2"],
        "profile_id",
        finder_cases,
    )
    output_identities = {
        "qa_raw": validate_exact_ids_and_splits(decoded["qa_raw"], qa_cases, "case_id", "qa_raw"),
        "finder_raw": validate_exact_ids_and_splits(
            decoded["finder_raw"], finder_cases, "profile_id", "finder_raw"
        ),
        "topic_predictions": validate_exact_ids_and_splits(
            decoded["topic_predictions"], topic_cases, "case_id", "topic_predictions"
        ),
    }
    for name in ("qa_raw", "finder_raw", "topic_predictions"):
        assert_versionable_raw_boundary(decoded[name], f"versionable.{name}")

    qa_rows = decoded["qa_pass1"]
    expected_qa = {
        split: runner.aggregate_qa([row for row in qa_rows if row["split"] == split])
        for split in ("dev", "test")
    }
    expected_qa["all"] = runner.aggregate_qa(qa_rows)
    if decoded["qa_metrics"].get("by_split") != expected_qa:
        raise AssertionError("versionable QA aggregate drift")
    finder_rows = decoded["finder_pass1"]
    expected_finder = {
        split: runner.aggregate_finder([row for row in finder_rows if row["split"] == split])
        for split in ("dev", "test", "sensitivity")
    }
    expected_finder["primary_dev_and_test"] = runner.aggregate_finder(
        [row for row in finder_rows if row["split"] in {"dev", "test"}]
    )
    expected_finder["all_including_sensitivity"] = runner.aggregate_finder(finder_rows)
    if decoded["finder_metrics"].get("by_split") != expected_finder:
        raise AssertionError("versionable Finder aggregate drift")
    vocabulary = list(decoded["topic_metrics"].get("controlled_vocabulary") or [])
    topic_rows = decoded["topic_predictions"]
    expected_topics = {
        split: runner.topic_aggregate(
            [row for row in topic_rows if row["split"] == split], vocabulary
        )
        for split in ("dev", "test")
    }
    expected_topics["all"] = runner.topic_aggregate(topic_rows, vocabulary)
    if decoded["topic_metrics"].get("by_split") != expected_topics:
        raise AssertionError("versionable topic aggregate drift")
    expected_macro_text = runner.manuscript_macro_text(
        receipt=receipt,
        corpus_identity=manifest.get("technical_corpus_identity"),
        keyword_index=manifest.get("temporary_keyword_index"),
    )
    if decoded["manuscript_macros"] != expected_macro_text:
        raise AssertionError("versionable manuscript macro drift")
    validate_validation_attestation(None)
    return {
        "status": "pass",
        "mode": "completed_versionable_package",
        "static": static,
        "qa_passes": qa_passes,
        "finder_passes": finder_passes,
        "output_identities": output_identities,
        "package_file_count": 2 + len(runner.OUTPUT_PATHS),
        "evaluation_source_commit": evaluation_source_commit,
        "rights_sensitive_raw_text_in_versionable_package": False,
        "validation_report_sha256": validation_report_sha256(
            manifest=manifest,
            receipt=receipt,
        ),
        "restricted_raw_validation": {
            "status": "recorded_attestation_only",
            "independently_rechecked_in_this_mode": False,
        },
        "boundary": (
            "Validated distributable AI-silver technical package. The prior strict "
            "full validation recorded a restricted-raw check in its attestation; "
            "this versionable-only mode cannot independently prove or repeat that check."
        ),
    }


def validate_completed(
    *,
    require_restricted: bool = True,
    require_attestation: bool = True,
) -> dict[str, Any]:
    static = validate_static()
    if not runner.RECEIPT_PATH.is_file():
        raise FileNotFoundError("freeze receipt is missing")
    receipt = json.loads(runner.RECEIPT_PATH.read_text(encoding="utf-8"))
    evaluation_source_commit = str(receipt.get("evaluation_source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", evaluation_source_commit):
        raise AssertionError("freeze receipt evaluation-source commit is invalid")
    if evaluation_source_commit != (receipt.get("git") or {}).get("head"):
        raise AssertionError("freeze receipt git identities disagree")
    if (receipt.get("git") or {}).get("evaluation_sources_clean_and_committed") is not True:
        raise AssertionError("freeze receipt was not created from clean committed evaluation sources")
    if receipt.get("frozen_dataset_identity") != runner.frozen_dataset_identity():
        raise AssertionError("freeze receipt dataset ID/split identity drift")
    if receipt.get("locked_validator_identity") != runner.locked_validator_identity():
        raise AssertionError("freeze receipt locked-validator identity drift")
    if receipt.get("static_validation_report_sha256") != runner.sha256_bytes(
        runner.canonical_json(static).encode("utf-8")
    ):
        raise AssertionError("freeze receipt static-validator report drift")
    if require_restricted and ((receipt.get("runtime") or {}).get("ocr_identity")) != runner.ocr_runtime_identity():
        raise AssertionError("OCR runtime/traineddata identity differs from the freeze")
    expected_frozen_paths = {runner.relative(path) for path in runner.frozen_input_paths()}
    if expected_frozen_paths != set(receipt.get("files", {})):
        raise AssertionError("freeze receipt inventory differs from code, data, DB, and v1 evidence inputs")
    if receipt.get("provider_environment_overrides") != runner.EVALUATION_ENVIRONMENT:
        raise AssertionError("freeze receipt provider environment drift")
    if receipt.get("technical_selection_predicate") != runner.TECHNICAL_SELECTION_PREDICATE:
        raise AssertionError("freeze receipt technical predicate drift")
    if receipt.get("public_projection_evaluated") is not False:
        raise AssertionError("freeze receipt implies public projection evaluation")
    if receipt.get("temporary_keyword_index_rebuild_required") is not True:
        raise AssertionError("freeze receipt does not require temporary keyword-index rebuild")
    for raw_path, metadata in receipt["files"].items():
        path = runner.ROOT / raw_path
        if runner.sha256_file(path) != metadata["sha256"] or path.stat().st_size != metadata["bytes"]:
            raise AssertionError(f"frozen file changed: {raw_path}")
    if runner.corpus_snapshot() != receipt["corpus_snapshot"]:
        raise AssertionError("logical paper/chunk corpus changed after the freeze")
    if runner.generation_artifact_inventory() != receipt.get("generation_artifact_inventory"):
        raise AssertionError("PDF/extraction/chunk generation-artifact inventory changed after the freeze")
    missing = [path.as_posix() for path in runner.OUTPUT_PATHS.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing completed outputs: {missing}")
    qa_cases = runner.read_jsonl(runner.QA_PATH)
    finder_cases = runner.read_jsonl(runner.FINDER_PATH)
    topic_cases_list = runner.read_jsonl(runner.TOPIC_PATH)
    qa_passes = validate_passes(
        runner.OUTPUT_PATHS["qa_pass1"],
        runner.OUTPUT_PATHS["qa_pass2"],
        "case_id",
        qa_cases,
    )
    finder_passes = validate_passes(
        runner.OUTPUT_PATHS["finder_pass1"],
        runner.OUTPUT_PATHS["finder_pass2"],
        "profile_id",
        finder_cases,
    )
    decoded_outputs: dict[str, Any] = {}
    for name, path in runner.OUTPUT_PATHS.items():
        if path.suffix == ".jsonl":
            decoded_outputs[name] = runner.read_jsonl(path)
        elif path.suffix == ".tex":
            decoded_outputs[name] = path.read_text(encoding="utf-8")
        else:
            decoded_outputs[name] = json.loads(path.read_text(encoding="utf-8"))
        assert_ai_silver_boundary(decoded_outputs[name], f"outputs.{name}")
        assert_no_absolute_filesystem_path(decoded_outputs[name], f"outputs.{name}")
    assert_no_absolute_filesystem_path(receipt, "freeze_receipt")
    output_identities = {
        "qa_raw": validate_exact_ids_and_splits(
            decoded_outputs["qa_raw"], qa_cases, "case_id", "qa_raw_outputs_v2.jsonl"
        ),
        "finder_raw": validate_exact_ids_and_splits(
            decoded_outputs["finder_raw"],
            finder_cases,
            "profile_id",
            "finder_raw_outputs_v2.jsonl",
        ),
        "topic_predictions": validate_exact_ids_and_splits(
            decoded_outputs["topic_predictions"],
            topic_cases_list,
            "case_id",
            "topic_predictions_v2.jsonl",
        ),
    }
    restricted_outputs: dict[str, list[dict[str, Any]]] = {}
    strict_recomputation: dict[str, Any] = {
        "status": "not_performed_without_operator_local_restricted_raw_outputs",
        "restricted_raw_validation_scope": "recorded_attestation_only_not_independent_proof",
    }
    if require_restricted:
        restricted_outputs = {
            name: runner.read_jsonl(path)
            for name, path in runner.RESTRICTED_OUTPUT_PATHS.items()
        }
        output_identities.update(
            {
                "qa_full_raw": validate_exact_ids_and_splits(
                    restricted_outputs["qa_full_raw"],
                    qa_cases,
                    "case_id",
                    "qa_full_raw_v2.jsonl",
                ),
                "finder_full_raw": validate_exact_ids_and_splits(
                    restricted_outputs["finder_full_raw"],
                    finder_cases,
                    "profile_id",
                    "finder_full_raw_v2.jsonl",
                ),
                "topic_full_raw": validate_exact_ids_and_splits(
                    restricted_outputs["topic_full_raw"],
                    topic_cases_list,
                    "case_id",
                    "topic_full_raw_v2.jsonl",
                ),
            }
        )
        strict_recomputation = {
            "status": "pass",
            **validate_strict_recomputation(
                decoded_outputs,
                restricted_outputs,
                qa_cases=qa_cases,
                finder_cases=finder_cases,
                topic_cases=topic_cases_list,
            ),
        }
    macro_text = decoded_outputs["manuscript_macros"]
    expected_macro_text = runner.manuscript_macro_text(
        receipt=receipt,
        corpus_identity=(decoded_outputs["manifest"] or {}).get("technical_corpus_identity"),
        keyword_index=(decoded_outputs["manifest"] or {}).get("temporary_keyword_index"),
    )
    if macro_text != expected_macro_text:
        raise AssertionError("manuscript macros do not match completed metric artifacts")
    observed_macros = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", macro_text))
    expected_macros = set(runner.MANUSCRIPT_MACRO_NAMES)
    if observed_macros != expected_macros:
        raise AssertionError(
            "manuscript macro contract drift: "
            f"missing={sorted(expected_macros - observed_macros)}, "
            f"unexpected={sorted(observed_macros - expected_macros)}"
        )
    if "AI-silver" not in macro_text or "human validation" not in macro_text:
        raise AssertionError("manuscript macros omit their evidence boundary")
    for prohibited_macro in (
        "VTwoTopicMicroPrecision",
        "VTwoTopicMicroFOne",
        "VTwoTopicExactMatch",
    ):
        if prohibited_macro in observed_macros:
            raise AssertionError(f"positive-only topic labels cannot support {prohibited_macro}")
    if any(row.get("retrieval_scope") != "technical" for row in decoded_outputs["qa_raw"]):
        raise AssertionError("Ask output scope drift")
    if any(row.get("retrieval_scope") != "technical" for row in decoded_outputs["finder_raw"]):
        raise AssertionError("Finder output scope drift")
    for name in ("qa_raw", "finder_raw", "topic_predictions"):
        rows = decoded_outputs[name]
        if any(
            row.get("publication_boundary")
            != "structural_only; rights-sensitive raw text retained outside versionable artifacts"
            for row in rows
        ):
            raise AssertionError(f"{name}: structural-only publication boundary drift")
        assert_versionable_raw_boundary(rows, f"outputs.{name}")
    for row in decoded_outputs["qa_raw"]:
        provenance = row.get("runtime_provenance") or {}
        if not provenance.get("generated_at"):
            raise AssertionError(f"Ask raw output lacks runtime timestamp: {row.get('case_id')}")
        for item in [*row.get("citations", []), *row.get("retrieved_chunks", [])]:
            for key in ("chunk_text_sha256", "effective_source_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(key) or "")):
                    raise AssertionError(f"Ask raw output lacks {key}: {row.get('case_id')}")
    for row in decoded_outputs["finder_raw"]:
        provenance = (row.get("full_finder") or {}).get("runtime_provenance") or {}
        if not provenance.get("generated_at"):
            raise AssertionError(f"Finder raw output lacks runtime timestamp: {row.get('profile_id')}")
        for item in (row.get("paired_retrieval") or {}).get("result_locators", []):
            for key in ("chunk_text_sha256", "effective_source_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(key) or "")):
                    raise AssertionError(f"Finder raw output lacks {key}: {row.get('profile_id')}")
    topic_cases = {row["case_id"]: row for row in runner.read_jsonl(runner.TOPIC_PATH)}
    for row in decoded_outputs["topic_predictions"]:
        source = row.get("source_locator") or {}
        frozen = topic_cases[row["case_id"]]["source_locator"]
        if source.get("chunk_id") != frozen.get("chunk_id"):
            raise AssertionError(f"Topic source chunk drift: {row.get('case_id')}")
        if source.get("chunk_text_sha256") != frozen.get("source_hash"):
            raise AssertionError(f"Topic raw source hash drift: {row.get('case_id')}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("effective_source_sha256") or "")):
            raise AssertionError(f"Topic effective source hash missing: {row.get('case_id')}")
    for name in ("qa_raw", "finder_raw", "topic_predictions"):
        serialized = json.dumps(decoded_outputs[name], ensure_ascii=False)
        if re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", serialized, flags=re.I):
            raise AssertionError(f"{name}: unredacted email address in sanitized output")
        assert_no_absolute_filesystem_path(serialized, f"outputs.{name}")
    bootstrap_contracts = {
        "qa_metrics": ("cluster_id", "named_source_paper"),
        "finder_metrics": ("cluster_id", "profile_family"),
        "topic_metrics": ("cluster_id", "paper"),
    }
    for name, (cluster_key, unit) in bootstrap_contracts.items():
        bootstrap = decoded_outputs[name].get("test_bootstrap_95_ci") or {}
        if (
            bootstrap.get("method") != "cluster_level_percentile_bootstrap"
            or bootstrap.get("cluster_key") != cluster_key
            or bootstrap.get("unit") != unit
            or int(bootstrap.get("cluster_count") or 0) <= 0
        ):
            raise AssertionError(f"{name}: cluster bootstrap contract drift")
    finder_splits = decoded_outputs["finder_metrics"].get("by_split") or {}
    if (finder_splits.get("test") or {}).get("profile_count") != 5:
        raise AssertionError("Finder primary held-out estimate includes the sensitivity mate")
    if (finder_splits.get("sensitivity") or {}).get("profile_count") != 1:
        raise AssertionError("Finder sensitivity profile is not reported separately")
    topic_metrics_serialized = json.dumps(decoded_outputs["topic_metrics"], ensure_ascii=False)
    for prohibited_key in ('"precision":', '"f1":', '"exact_match_rate":', '"false_positive_case_ids":'):
        if prohibited_key in topic_metrics_serialized:
            raise AssertionError(
                f"positive-only topic labels were misinterpreted as closed-world negatives: {prohibited_key}"
            )
    topic_conclusion = decoded_outputs["topic_metrics"].get("public_validation_conclusion", "")
    if "No public" not in topic_conclusion:
        raise AssertionError("topic artifact lacks explicit no-public-validation conclusion")
    qa_pass1_rows = decoded_outputs["qa_pass1"]
    expected_qa_by_split = {
        split: runner.aggregate_qa([row for row in qa_pass1_rows if row["split"] == split])
        for split in ("dev", "test")
    }
    expected_qa_by_split["all"] = runner.aggregate_qa(qa_pass1_rows)
    if decoded_outputs["qa_metrics"].get("by_split") != expected_qa_by_split:
        raise AssertionError("QA aggregate counts/metrics do not recompute from pass 1")

    finder_pass1_rows = decoded_outputs["finder_pass1"]
    expected_finder_by_split = {
        split: runner.aggregate_finder(
            [row for row in finder_pass1_rows if row["split"] == split]
        )
        for split in ("dev", "test", "sensitivity")
    }
    expected_finder_by_split["primary_dev_and_test"] = runner.aggregate_finder(
        [row for row in finder_pass1_rows if row["split"] in {"dev", "test"}]
    )
    expected_finder_by_split["all_including_sensitivity"] = runner.aggregate_finder(
        finder_pass1_rows
    )
    if decoded_outputs["finder_metrics"].get("by_split") != expected_finder_by_split:
        raise AssertionError("Finder aggregate counts/metrics do not recompute from pass 1")

    topic_prediction_rows = decoded_outputs["topic_predictions"]
    topic_vocabulary = list(decoded_outputs["topic_metrics"].get("controlled_vocabulary") or [])
    expected_topic_by_split = {
        split: runner.topic_aggregate(
            [row for row in topic_prediction_rows if row["split"] == split],
            topic_vocabulary,
        )
        for split in ("dev", "test")
    }
    expected_topic_by_split["all"] = runner.topic_aggregate(
        topic_prediction_rows,
        topic_vocabulary,
    )
    if decoded_outputs["topic_metrics"].get("by_split") != expected_topic_by_split:
        raise AssertionError("Topic aggregate counts/metrics do not recompute from predictions")
    ocr_boundary = decoded_outputs["ocr_results"].get("claim_boundary", "")
    if "not TTLAB corpus OCR accuracy" not in ocr_boundary:
        raise AssertionError("OCR artifact overstates the synthetic fixture")
    ocr = decoded_outputs["ocr_results"]
    if ocr.get("pipeline") != "app.ingestion.pdf_parser.extract_pdf_text":
        raise AssertionError("OCR output did not record the full parser pipeline")
    if ocr.get("parser_limits") != {"max_pdf_bytes": 5_242_880, "max_pdf_pages": 1}:
        raise AssertionError("OCR parser limits drift")
    frozen_ocr = ((receipt.get("runtime") or {}).get("ocr_identity") or {})
    provider = ocr.get("provider") or {}
    if provider.get("deterministic_configuration") != frozen_ocr.get("configuration"):
        raise AssertionError("OCR output configuration differs from the frozen runtime")
    tesseract_lines = str(frozen_ocr.get("tesseract") or "").splitlines()
    if not tesseract_lines or provider.get("version") != tesseract_lines[0].strip():
        raise AssertionError("OCR output provider version differs from the frozen executable")
    language_data = (provider.get("deterministic_configuration") or {}).get("language_data") or {}
    if language_data.get("status") != "available" or not re.fullmatch(
        r"[0-9a-f]{64}", str(language_data.get("sha256") or "")
    ):
        raise AssertionError("OCR traineddata identity is unavailable or unhashed")
    if '"resolved_path":' in json.dumps(ocr, ensure_ascii=False):
        raise AssertionError("OCR versionable output leaks a host traineddata path")
    for pass_name in ("first_pass", "second_pass"):
        pipeline_pass = ocr.get(pass_name) or {}
        config = pipeline_pass.get("extraction_config") or {}
        diagnostics = pipeline_pass.get("diagnostics") or {}
        pages = pipeline_pass.get("pages") or []
        artifacts = pipeline_pass.get("persisted_artifacts") or {}
        if config.get("run_ocr") is not True or config.get("max_pdf_bytes") != 5_242_880:
            raise AssertionError(f"OCR {pass_name} extraction configuration drift")
        if config.get("max_pdf_pages") != 1 or config.get("expected_title") != "TTLAB OCR PIPELINE FIXTURE V2":
            raise AssertionError(f"OCR {pass_name} parser/title configuration drift")
        if diagnostics.get("content_type") != "scanned" or diagnostics.get("possible_scanned_pdf") is not True:
            raise AssertionError(f"OCR {pass_name} did not exercise scanned-page classification")
        if diagnostics.get("ocr_requested") is not True or diagnostics.get("ocr_status") != "completed":
            raise AssertionError(f"OCR {pass_name} did not complete OCR through the parser")
        if (diagnostics.get("pdf_title_match") or {}).get("status") != "matched":
            raise AssertionError(f"OCR {pass_name} title diagnostic did not match")
        if len(pages) != 1 or pages[0].get("content_class") != "scanned":
            raise AssertionError(f"OCR {pass_name} page diagnostics drift")
        expected_ocr_configuration = frozen_ocr.get("configuration")
        if config.get("ocr_configuration") != expected_ocr_configuration:
            raise AssertionError(f"OCR {pass_name} extraction configuration differs from the freeze")
        if diagnostics.get("ocr_configuration") != expected_ocr_configuration:
            raise AssertionError(f"OCR {pass_name} diagnostics configuration differs from the freeze")
        if pages[0].get("ocr_configuration") != expected_ocr_configuration or (
            pages[0].get("provenance") or {}
        ).get("ocr_configuration") != expected_ocr_configuration:
            raise AssertionError(f"OCR {pass_name} page configuration differs from the freeze")
        if pages[0].get("extraction_method") != "ocr" or pages[0].get("ocr_status") != "completed":
            raise AssertionError(f"OCR {pass_name} did not dispatch OCR through the parser")
        if artifacts.get("manifest_readback_matches_returned_result") is not True:
            raise AssertionError(f"OCR {pass_name} manifest did not pass atomic readback")
        for key in ("text_sha256", "manifest_sanitized_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(artifacts.get(key) or "")):
                raise AssertionError(f"OCR {pass_name} lacks {key}")
    for key in (
        "repeat_run_text_identical",
        "repeat_run_text_artifact_identical",
        "repeat_run_configuration_identical",
        "repeat_run_sanitized_pipeline_result_identical",
    ):
        if (ocr.get("metrics") or {}).get(key) is not True:
            raise AssertionError(f"OCR determinism check failed: {key}")
    manifest = decoded_outputs["manifest"]
    validate_manifest_output_inventory(manifest, require_attestation=require_attestation)
    validate_restricted_inventory(manifest, require_files=require_restricted)
    if manifest.get("frozen_dataset_identity") != receipt.get("frozen_dataset_identity"):
        raise AssertionError("manifest/receipt frozen dataset identities disagree")
    if manifest.get("locked_validator_identity") != receipt.get("locked_validator_identity"):
        raise AssertionError("manifest/receipt locked-validator identities disagree")
    for field in ("public_validation_claimed", "entailment_claimed", "human_validation_claimed"):
        if manifest.get(field) is not False:
            raise AssertionError(f"manifest boundary failed: {field}")
    if manifest.get("v1_artifacts_overwritten") is not False:
        raise AssertionError("manifest must retain v1 artifacts")
    if manifest.get("tracked_database_mutated") is not False:
        raise AssertionError("tracked database mutation was claimed")
    if manifest.get("public_projection_exercised") is not False:
        raise AssertionError("manifest implies public projection execution")
    if manifest.get("technical_selection_predicate") != runner.TECHNICAL_SELECTION_PREDICATE:
        raise AssertionError("manifest technical predicate drift")
    if manifest.get("public_selection_predicate_recorded_not_tested") != runner.PUBLIC_SELECTION_PREDICATE:
        raise AssertionError("manifest public predicate drift")
    if manifest.get("provider_environment_overrides") != runner.EVALUATION_ENVIRONMENT:
        raise AssertionError("manifest provider environment drift")
    if manifest.get("evaluation_source_commit") != receipt.get("evaluation_source_commit"):
        raise AssertionError("manifest evaluation-source commit drift")
    if manifest.get("release_contains_rights_sensitive_raw_text") is not False:
        raise AssertionError("manifest permits rights-sensitive raw text in release artifacts")
    index = manifest.get("temporary_keyword_index") or {}
    if index.get("database_scope") != "temporary_copy_only":
        raise AssertionError("keyword index was not confined to the temporary database")
    rebuild = index.get("rebuild_result") or {}
    health = index.get("health") or {}
    reconciliation = runner.validate_generation_reconciliation(index.get("generation_reconciliation"))
    if rebuild.get("completeness_status") not in {"complete", "fallback_only"}:
        raise AssertionError("temporary keyword index lacks an approved completeness status")
    corpus_identity = manifest.get("technical_corpus_identity") or {}
    if corpus_identity.get("technical_selection_predicate") != runner.TECHNICAL_SELECTION_PREDICATE:
        raise AssertionError("technical corpus generation-link predicate drift")
    if int(corpus_identity.get("eligible_chunk_count") or 0) <= 0 or int(
        corpus_identity.get("eligible_paper_count") or 0
    ) <= 0:
        raise AssertionError("technical corpus is empty after generation-link reconciliation")
    if int(reconciliation["reconciled"]) + int(reconciliation["already_current"]) < int(
        corpus_identity["eligible_paper_count"]
    ):
        raise AssertionError("generation reconciliation does not account for every eligible paper")
    if rebuild.get("corpus_snapshot_hash") != corpus_identity.get("snapshot_hash"):
        raise AssertionError("temporary keyword index/corpus identity mismatch")
    if rebuild.get("eligible_chunks") != corpus_identity.get("eligible_chunk_count"):
        raise AssertionError("temporary keyword index eligible chunk count mismatch")
    if rebuild.get("eligible_papers") != corpus_identity.get("eligible_paper_count"):
        raise AssertionError("temporary keyword index eligible paper count mismatch")
    if rebuild.get("completeness_status") == "complete" and (
        health.get("status") != "ready" or health.get("coverage_ratio") != 1.0
    ):
        raise AssertionError("temporary keyword index is not complete and ready")
    provenance_validation = runner.validate_runtime_provenance_outputs(corpus_identity, index)
    if provenance_validation != manifest.get("runtime_provenance_validation"):
        raise AssertionError("manifest runtime-provenance validation drift")
    if (provenance_validation.get("code_identity") or {}).get("git_commit") != receipt.get(
        "evaluation_source_commit"
    ):
        raise AssertionError("runtime backend commit differs from the frozen evaluation source commit")
    if provenance_validation.get("record_count") != len(decoded_outputs["qa_raw"]) + len(
        decoded_outputs["finder_raw"]
    ):
        raise AssertionError("runtime provenance record count mismatch")
    for metric_name in ("qa_metrics", "finder_metrics", "topic_metrics", "ocr_results"):
        serialized_metrics = json.dumps(decoded_outputs[metric_name], ensure_ascii=False)
        if '"runtime_provenance"' in serialized_metrics or '"generated_at"' in serialized_metrics:
            raise AssertionError(f"{metric_name}: runtime timestamps leaked into deterministic metrics")
    deterministic_reference: dict[str, Any] = {
        "comparison_required": runner.OUT_DIR != runner.CANONICAL_OUT_DIR.resolve(),
        "canonical_path": runner.CANONICAL_OUT_RELATIVE.as_posix(),
        "matched": None,
        "files": {},
    }
    if deterministic_reference["comparison_required"]:
        for filename in runner.DETERMINISTIC_COMPARISON_FILENAMES:
            reference = runner.CANONICAL_OUT_DIR / filename
            reproduced = runner.OUT_DIR / filename
            if not reference.is_file():
                raise FileNotFoundError(f"canonical deterministic reference is missing: {reference}")
            reference_hash = runner.normalized_artifact_sha256(reference)
            reproduced_hash = runner.normalized_artifact_sha256(reproduced)
            deterministic_reference["files"][filename] = {
                "canonical_normalized_sha256": reference_hash,
                "reproduced_normalized_sha256": reproduced_hash,
                "matched": reference_hash == reproduced_hash,
                "normalization": "timestamp_fields_excluded_only",
            }
        deterministic_reference["matched"] = all(
            item["matched"] for item in deterministic_reference["files"].values()
        )
        if not deterministic_reference["matched"]:
            raise AssertionError("run-local v2 metric artifacts do not match the canonical clean-source reference")
    report = {
        "status": "pass",
        "static": static,
        "qa_passes": qa_passes,
        "finder_passes": finder_passes,
        "output_identities": output_identities,
        "artifact_count": len(runner.OUTPUT_PATHS),
        "restricted_raw_files_checked": require_restricted,
        "strict_recomputation": strict_recomputation,
        "deterministic_reference": deterministic_reference,
        "boundary": "AI-silver technical evaluation; no human, entailment, public, feasibility, or corpus-OCR validation claim.",
    }
    if require_attestation:
        validate_validation_attestation(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument(
        "--versionable-only",
        action="store_true",
        help="validate a completed canonical bundle without requiring operator-local restricted raw files",
    )
    parser.add_argument(
        "--write-attestation",
        action="store_true",
        help="validate the complete local package once and write its post-validation attestation",
    )
    args = parser.parse_args()
    if args.static_only and (args.versionable_only or args.write_attestation):
        parser.error("--static-only cannot be combined with completed-package modes")
    if args.versionable_only and args.write_attestation:
        parser.error("--versionable-only cannot write a full-validation attestation")
    if args.static_only:
        report = validate_static()
    elif args.versionable_only:
        report = validate_versionable_package()
    elif args.write_attestation:
        report = validate_completed(require_restricted=True, require_attestation=False)
        write_validation_attestation(report)
        report = validate_completed(require_restricted=True, require_attestation=True)
    else:
        report = validate_completed(require_restricted=True, require_attestation=True)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
