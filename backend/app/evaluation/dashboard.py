from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, func, select

from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation
from app.indexing.embedder import corpus_descriptor, current_code_commit, eligible_chunks
from app.indexing.retriever import DEFAULT_RETRIEVER_CONFIG

DEFAULT_EVALUATION_DIR = Path("data/evaluation")
ROOT = Path(__file__).resolve().parents[3]

RESULT_FILES = {
    "retrieval": "retrieval_eval_results.json",
    "qa": "qa_eval_results.json",
    "extension": "extension_eval_results.json",
    "artifact": "artifact_eval_results.json",
}

CURRENT_RESULT_FILES = {
    "retrieval": ROOT / "artifacts" / "phase2" / "retrieval" / "summary.json",
    "qa": ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    "extension": ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    "artifact": ROOT
    / "artifacts"
    / "phase4"
    / "generated_output_review"
    / "generated_output_review_summary.json",
}
V2_PACKAGE_RELATIVE = Path("artifacts/peer_review_remediation/v2")
V2_PACKAGE_DIR = ROOT / V2_PACKAGE_RELATIVE
V2_MANIFEST_PATH = V2_PACKAGE_DIR / "manifest_v2.json"
V2_RECEIPT_PATH = V2_PACKAGE_DIR / "freeze_receipt_v2.json"
V2_ATTESTATION_PATH = V2_PACKAGE_DIR / "validation_attestation_v2.json"
V2_RESULT_FILES = {
    "qa": V2_PACKAGE_DIR / "qa_metrics_v2.json",
    "finder": V2_PACKAGE_DIR / "finder_metrics_v2.json",
    "topics": V2_PACKAGE_DIR / "topic_metrics_v2.json",
    "ocr": V2_PACKAGE_DIR / "ocr_fixture_results_v2.json",
}
V2_OUTPUT_FILENAMES = frozenset(
    {
        "qa_raw_outputs_v2.jsonl",
        "qa_review_pass1_v2.jsonl",
        "qa_review_pass2_v2.jsonl",
        "qa_disagreements_v2.json",
        "qa_metrics_v2.json",
        "finder_raw_outputs_v2.jsonl",
        "finder_review_pass1_v2.jsonl",
        "finder_review_pass2_v2.jsonl",
        "finder_disagreements_v2.json",
        "finder_metrics_v2.json",
        "topic_predictions_v2.jsonl",
        "topic_metrics_v2.json",
        "ocr_fixture_results_v2.json",
        "manuscript_macros_v2.tex",
    }
)
V2_PACKAGE_FILENAMES = frozenset(
    {*V2_OUTPUT_FILENAMES, V2_MANIFEST_PATH.name, V2_RECEIPT_PATH.name, V2_ATTESTATION_PATH.name}
)
RETRIEVAL_SILVER_PATH = ROOT / "data" / "evaluation" / "retrieval_silver_v1.jsonl"


def build_evaluation_dashboard(
    session: Session,
    evaluation_dir: Path = DEFAULT_EVALUATION_DIR,
) -> dict[str, Any]:
    if (
        evaluation_dir == DEFAULT_EVALUATION_DIR
        and (
            V2_MANIFEST_PATH.is_file()
            or (
                RETRIEVAL_SILVER_PATH.is_file()
                and all(path.is_file() for path in CURRENT_RESULT_FILES.values())
            )
        )
    ):
        return build_current_evaluation_dashboard(session)
    retrieval = parse_retrieval_results(evaluation_dir / RESULT_FILES["retrieval"])
    qa = parse_qa_results(evaluation_dir / RESULT_FILES["qa"])
    extension = parse_extension_results(evaluation_dir / RESULT_FILES["extension"])
    artifact = parse_artifact_results(evaluation_dir / RESULT_FILES["artifact"])
    return {
        "retrieval": retrieval,
        "qa": qa,
        "extension": extension,
        "artifact": artifact,
        "human_review_templates": template_availability(evaluation_dir),
        "overall_quality": overall_quality(session),
        "result_files": {
            key: {
                "path": repository_logical_path(evaluation_dir / filename),
                "exists": (evaluation_dir / filename).exists(),
                "last_modified": file_timestamp(evaluation_dir / filename),
            }
            for key, filename in RESULT_FILES.items()
        },
    }


def build_current_evaluation_dashboard(session: Session) -> dict[str, Any]:
    """Expose the executed, versioned experiment artefacts used by the manuscripts."""

    freshness = evaluation_freshness(session)
    result = {
        "evaluation_label": "AI-reviewed silver offline evaluation; no recruited human participants",
        "reviewer_type": "ai",
        "human_validation": False,
        "retrieval": parse_current_retrieval(CURRENT_RESULT_FILES["retrieval"]),
        "qa": parse_current_qa(CURRENT_RESULT_FILES["qa"]),
        "extension": parse_current_extension(CURRENT_RESULT_FILES["extension"]),
        "artifact": parse_current_review(CURRENT_RESULT_FILES["artifact"]),
        "human_review_templates": template_availability(DEFAULT_EVALUATION_DIR),
        "overall_quality": overall_quality(session),
        "result_files": {
            key: {
                "path": repository_logical_path(path),
                "exists": path.exists(),
                "last_modified": file_timestamp(path),
            }
            for key, path in CURRENT_RESULT_FILES.items()
        },
        "freshness": freshness,
        "evaluation_status": freshness["status"],
        "peer_review_remediation_v2": parse_v2_evidence_package(
            freshness["peer_review_remediation_v2"]
        ),
    }
    for key in ("retrieval", "qa", "extension", "artifact"):
        result[key]["freshness_status"] = freshness["artifacts"][key]["status"]
        if freshness["artifacts"][key]["status"] != "current":
            result[key]["status"] = "historical"
    return result


def parse_v2_evidence_package(
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = freshness or v2_package_freshness()
    if freshness["status"] != "current":
        return {
            "status": freshness["status"],
            "evidence_tier": "ai_silver",
            "human_validation": False,
            "manifest_path": repository_logical_path(V2_MANIFEST_PATH),
            "freshness": freshness,
        }
    manifest_result = read_result(V2_MANIFEST_PATH)
    if manifest_result["status"] != "available":
        return {
            "status": manifest_result["status"],
            "evidence_tier": "ai_silver",
            "human_validation": False,
            "manifest_path": repository_logical_path(V2_MANIFEST_PATH),
        }
    manifest = manifest_result["payload"]
    qa = read_result(V2_RESULT_FILES["qa"])
    finder = read_result(V2_RESULT_FILES["finder"])
    topics = read_result(V2_RESULT_FILES["topics"])
    ocr = read_result(V2_RESULT_FILES["ocr"])

    def split_summary(result: dict[str, Any], split: str = "test") -> dict[str, Any] | None:
        if result.get("status") != "available":
            return None
        payload = result.get("payload") or {}
        value = (payload.get("by_split") or {}).get(split)
        return value if isinstance(value, dict) else None

    return {
        "status": "current",
        "package_status": str(manifest.get("status") or "invalid"),
        "evaluation_id": manifest.get("evaluation_id"),
        "evidence_tier": "ai_silver",
        "reviewer_type": (manifest.get("reviewer") or {}).get("reviewer_type"),
        "human_validation": bool(manifest.get("human_validation_claimed")),
        "entailment_claimed": bool(manifest.get("entailment_claimed")),
        "technical_scope_only": bool(manifest.get("technical_scope_only")),
        "public_projection_exercised": bool(manifest.get("public_projection_exercised")),
        "qa_test": split_summary(qa),
        "finder_test": split_summary(finder),
        "topics_test": split_summary(topics),
        "ocr": ocr.get("payload") if ocr.get("status") == "available" else None,
        "claim_boundary": manifest.get("claim_boundary"),
        "validation_attestation": {
            "path": repository_logical_path(V2_ATTESTATION_PATH),
            "status": "validated",
            "restricted_raw_validation": (
                "recorded by the prior strict full validation; not independently "
                "rechecked from this versionable package"
            ),
        },
        "freshness": freshness,
        "manifest_path": repository_logical_path(V2_MANIFEST_PATH),
        "result_files": {
            key: {
                "path": repository_logical_path(path),
                "exists": path.is_file(),
                "last_modified": file_timestamp(path),
            }
            for key, path in V2_RESULT_FILES.items()
        },
    }


def parse_current_retrieval(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_retrieval_results(path)
    payload = result["payload"]
    silver_cases = [
        json.loads(line)
        for line in RETRIEVAL_SILVER_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    answerable_test_count = sum(
        row.get("split") == "test" and row.get("answerability") == "answerable"
        for row in silver_cases
    )
    keyword = payload["test_results"]["keyword"]
    tuned = payload["test_results"]["tuned_hybrid"]
    return {
        **base_status(path, "available"),
        "question_count": payload["dataset"]["case_count"],
        "development_count": payload["dataset"]["dev_count"],
        "test_count": payload["dataset"]["test_count"],
        "answerable_test_count": answerable_test_count,
        "unanswerable_test_count": payload["dataset"]["test_count"] - answerable_test_count,
        "recall_at_3": keyword["set_recall_at_3"]["estimate"],
        "recall_at_5": keyword["set_recall_at_5"]["estimate"],
        "recall_at_10": keyword["set_recall_at_10"]["estimate"],
        "mrr": keyword["mrr"]["estimate"],
        "ndcg_at_10": keyword["ndcg_at_10"]["estimate"],
        "reported_mode": "keyword (strongest held-out estimate)",
        "tuned_hybrid_recall_at_10": tuned["set_recall_at_10"]["estimate"],
        "tuned_hybrid_mrr": tuned["mrr"]["estimate"],
        "unanswerable_false_positive_rate": keyword["unanswerable_false_positive_rate"]["estimate"],
        "reviewer_type": "ai",
        "dataset_label": payload["dataset"]["label"],
        "statistical_conclusion": "No Holm-corrected tuned-hybrid comparison rejected the null hypothesis.",
    }


def parse_current_qa(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_qa_results(path)
    payload = result["payload"]
    metrics = payload["metrics"]
    counts = payload["counts"]
    return {
        **base_status(path, "available"),
        "question_count": payload["case_count"],
        "answer_count": payload["case_count"],
        "claim_count": counts["claim_count"],
        "citation_count": counts["citation_links"],
        "supported_claim_rate": metrics["supported_claim_rate"],
        "citation_correctness": metrics["citation_precision_correctness"],
        "citation_completeness": metrics["citation_completeness"],
        "answer_point_coverage": metrics["answer_point_coverage"],
        "unsupported_claim_rate": metrics["unsupported_claim_rate"],
        "unanswerable_abstention_rate": metrics["unanswerable_abstention_rate"],
        "reviewer_type": payload["reviewer_type"],
        # Retained compatibility fields for existing clients.
        "cited_gold_paper_count": 0,
        "grounding_counts": {
            "supported": counts["supported_claims"],
            "partial": counts["partially_supported_claims"],
            "unsupported": counts["unsupported_claims"],
        },
    }


def parse_current_extension(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_extension_results(path)
    payload = result["payload"]
    comparison = payload["metrics"]["arm_comparison"]
    delta = comparison["full_minus_baseline_relevance"]
    reviewed = payload["metrics"]["full_finder"]["reviewed_items"]
    unresolved_feasibility = int(
        payload.get("metrics", {}).get("error_taxonomy", {}).get("unresolved_feasibility_constraint") or 0
    )
    return {
        **base_status(path, "available"),
        "case_count": payload["profile_coverage"]["profile_count"],
        "recommendation_count": reviewed,
        "citation_coverage": 1.0,
        "warnings_count": unresolved_feasibility,
        "feasibility_status": "partial" if unresolved_feasibility else "complete",
        "unresolved_feasibility_constraint_count": unresolved_feasibility,
        "evidence_only_relevance": comparison["baseline_mean_relevance_score"],
        "full_finder_relevance": comparison["full_finder_mean_relevance_score"],
        "relevance_difference": delta["estimate"],
        "relevance_difference_ci": [delta["ci_lower"], delta["ci_upper"]],
        "reviewer_type": payload["reviewer_type"],
        "proxy_notice": "Synthetic-profile AI proxy review; not student or supervisor validation.",
        "grounding_counts": empty_grounding_counts(),
    }


def evaluation_freshness(session: Session) -> dict[str, Any]:
    """Validate each evidence package against the identities it recorded.

    V1 artifacts did not freeze a uniform identity contract, so they remain
    historical unless every identity they recorded can be checked. V2 is
    validated from its freeze receipt and output manifest; current HEAD is not
    used, which means a later docs-only commit cannot stale valid evidence.
    """

    current_corpus = corpus_descriptor(session, eligible_chunks(session))
    current_config_hash = hashlib.sha256(
        json.dumps(DEFAULT_RETRIEVER_CONFIG.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifacts: dict[str, dict[str, Any]] = {}
    for key, path in CURRENT_RESULT_FILES.items():
        result = read_result(path)
        if result["status"] != "available":
            artifacts[key] = {"status": result["status"], "path": repository_logical_path(path)}
            continue
        payload = result["payload"]
        recorded_corpus = recursive_value(payload, {"snapshot_hash", "corpus_snapshot_hash"})
        recorded_config = recursive_value(payload, {"configuration_hash", "config_hash", "retriever_config_hash"})
        recorded_code_tree = recursive_value(payload, {"git_tree", "backend_tree", "code_tree"})
        checks = {
            "corpus": "match" if recorded_corpus == current_corpus["snapshot_hash"] else "missing" if not recorded_corpus else "mismatch",
            "configuration": "match" if recorded_config == current_config_hash else "missing" if not recorded_config else "mismatch",
            # A commit is deliberately not treated as a code identity. These
            # v1 artifacts lack a consistently recorded backend-tree hash.
            "code": "unverifiable" if not recorded_code_tree else "recorded_not_reconstructed",
        }
        status = "current" if all(value == "match" for value in checks.values()) else "historical"
        artifacts[key] = {
            "status": status,
            "checks": checks,
            "recorded_code_tree": recorded_code_tree,
            "recorded_corpus_snapshot_hash": recorded_corpus,
            "recorded_configuration_hash": recorded_config,
            "path": repository_logical_path(path),
        }
    v2 = v2_package_freshness()
    overall = (
        v2["status"]
        if v2["status"] in {"current", "stale", "invalid"}
        else "current" if artifacts and all(item["status"] == "current" for item in artifacts.values()) else "historical"
    )
    return {
        "status": overall,
        "notice": (
            "Evidence is current only when its own frozen code, corpus, configuration, output, and release identities validate. "
            "A repository HEAD change alone is not a freshness signal."
        ),
        "current_corpus_snapshot_hash": current_corpus["snapshot_hash"],
        "current_configuration_hash": current_config_hash,
        "artifacts": artifacts,
        "peer_review_remediation_v2": v2,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def v2_versionable_validation_report_portion(
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    *,
    manifest_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Rebuild the release-verifiable portion bound by the attestation digest."""

    return {
        "schema_version": 1,
        "evaluation_id": "peer-review-remediation-v2",
        "mode": "completed_versionable_package",
        "manifest_sha256": sha256_file(manifest_path),
        "freeze_receipt_sha256": sha256_file(receipt_path),
        "versionable_output_inventory_sha256": hashlib.sha256(
            canonical_json(manifest.get("outputs") or {}).encode("utf-8")
        ).hexdigest(),
        "evaluation_source_commit": manifest.get("evaluation_source_commit"),
        "frozen_dataset_identity_sha256": hashlib.sha256(
            canonical_json(receipt.get("frozen_dataset_identity") or {}).encode("utf-8")
        ).hexdigest(),
        "locked_validator_identity_sha256": hashlib.sha256(
            canonical_json(receipt.get("locked_validator_identity") or {}).encode("utf-8")
        ).hexdigest(),
        "package_file_count": len(V2_PACKAGE_FILENAMES),
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


def v2_versionable_validation_report_sha256(
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    *,
    manifest_path: Path,
    receipt_path: Path,
) -> str:
    portion = v2_versionable_validation_report_portion(
        manifest,
        receipt,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
    )
    return hashlib.sha256(canonical_json(portion).encode("utf-8")).hexdigest()


def repository_logical_path(path: Path) -> str:
    """Return a public locator without disclosing the operator's filesystem root."""

    root = ROOT.resolve()
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if candidate == root:
        return "."
    if root in candidate.parents:
        return candidate.relative_to(root).as_posix()
    return path.name or "outside_repository"


def resolve_recorded_path(raw_path: str) -> Path | None:
    candidate = (ROOT / raw_path).resolve()
    root = ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def public_recorded_locator(raw_path: str) -> str:
    candidate = resolve_recorded_path(raw_path)
    return repository_logical_path(candidate) if candidate is not None else "unsafe_repository_path"


def v2_package_freshness(manifest_path: Path | None = None) -> dict[str, Any]:
    """Verify exact v2 inventories and its strict post-validation attestation."""

    path = manifest_path or V2_MANIFEST_PATH
    if not path.is_file():
        return {"status": "not_run", "path": repository_logical_path(path)}
    errors: list[str] = []
    identity_mismatches: dict[str, list[str]] = {
        "code": [],
        "corpus": [],
        "configuration": [],
        "release": [],
    }

    def read_object(candidate: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{label}_unreadable:{type(exc).__name__}")
            return {}
        if not isinstance(value, dict):
            errors.append(f"{label}_not_object")
            return {}
        return value

    package_dir = path.parent
    manifest = read_object(path, "manifest")
    expected_manifest_locator = (V2_PACKAGE_RELATIVE / V2_MANIFEST_PATH.name).as_posix()
    if repository_logical_path(path) != expected_manifest_locator:
        errors.append("manifest_noncanonical_path")
    observed_names: set[str] = set()
    if package_dir.is_symlink() or not package_dir.is_dir():
        errors.append("package_directory_missing_or_symlinked")
    else:
        try:
            package_entries = list(package_dir.iterdir())
        except OSError as exc:
            errors.append(f"package_directory_unreadable:{type(exc).__name__}")
            package_entries = []
        for item in package_entries:
            observed_names.add(item.name)
            if item.is_symlink() or not item.is_file():
                errors.append(f"package_non_regular_or_nested_entry:{item.name}")
    if observed_names != V2_PACKAGE_FILENAMES:
        errors.append("package_filename_inventory_mismatch")
    if any("full_raw" in name.lower() for name in observed_names):
        errors.append("rights_sensitive_raw_output_in_package")
    if (
        manifest.get("evaluation_id") != "peer-review-remediation-v2"
        or manifest.get("status") != "completed"
        or manifest.get("technical_scope_only") is not True
    ):
        errors.append("manifest_identity_invalid")
    for field in (
        "public_validation_claimed",
        "public_projection_exercised",
        "entailment_claimed",
        "human_validation_claimed",
        "v1_artifacts_overwritten",
        "tracked_database_mutated",
        "release_contains_rights_sensitive_raw_text",
    ):
        if manifest.get(field) is not False:
            errors.append(f"manifest_boundary_invalid:{field}")
    reviewer = manifest.get("reviewer") or {}
    restricted_policy = manifest.get("restricted_raw_outputs") or {}
    if reviewer.get("reviewer_type") != "ai" or reviewer.get("human_review") is not False:
        errors.append("manifest_reviewer_boundary_invalid")
    if (
        not str(manifest.get("technical_selection_predicate") or "")
        or not str(manifest.get("public_selection_predicate_recorded_not_tested") or "")
        or manifest.get("provider_environment_overrides")
        != {
            "TTLAB_ALLOWED_LLM_PROVIDERS": '["offline_extractive"]',
            "TTLAB_DEFAULT_LLM_PROVIDER": "offline_extractive",
        }
    ):
        errors.append("manifest_execution_boundary_invalid")
    if (
        restricted_policy.get("required") is not True
        or restricted_policy.get("retained_locally") is not True
        or restricted_policy.get("committed") is not False
        or restricted_policy.get("release_included") is not False
        or restricted_policy.get("lawful_local_corpus_access_required_for_exact_reproduction")
        is not True
    ):
        errors.append("manifest_restricted_raw_boundary_invalid")

    expected_receipt_locator = (V2_PACKAGE_RELATIVE / V2_RECEIPT_PATH.name).as_posix()
    freeze_raw = str(manifest.get("freeze_receipt") or "")
    receipt_path = resolve_recorded_path(freeze_raw) if freeze_raw else None
    if freeze_raw != expected_receipt_locator or receipt_path is None or not receipt_path.is_file():
        errors.append("freeze_receipt_missing_unsafe_or_noncanonical")
        receipt: dict[str, Any] = {}
    else:
        receipt = read_object(receipt_path, "freeze_receipt")
        expected_receipt_hash = str(manifest.get("freeze_receipt_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_receipt_hash) or (
            sha256_file(receipt_path) != expected_receipt_hash
        ):
            errors.append("freeze_receipt_hash_mismatch")

    frozen_files = receipt.get("files") if isinstance(receipt, dict) else None
    if not isinstance(frozen_files, dict) or not frozen_files:
        errors.append("frozen_file_inventory_missing")
    else:
        for raw_path, metadata in frozen_files.items():
            if (
                not isinstance(raw_path, str)
                or not isinstance(metadata, dict)
                or set(metadata) != {"sha256", "bytes"}
            ):
                errors.append("frozen_file_inventory_invalid")
                continue
            recorded_path = resolve_recorded_path(raw_path)
            expected_hash = str(metadata.get("sha256") or "")
            expected_bytes = metadata.get("bytes")
            mismatch = (
                recorded_path is None
                or not recorded_path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or (recorded_path.is_file() and recorded_path.stat().st_size != expected_bytes)
                or (recorded_path.is_file() and sha256_file(recorded_path) != expected_hash)
            )
            if not mismatch:
                continue
            if raw_path.startswith("backend/app/") or raw_path.endswith(
                ("run_peer_review_remediation_v2.py", "validate_peer_review_remediation_v2.py")
            ):
                category = "code"
            elif raw_path == "data/papers.db" or raw_path.endswith(
                (".jsonl", "ocr_scanned_fixture_v2.pdf")
            ):
                category = "corpus"
            else:
                category = "configuration"
            identity_mismatches[category].append(public_recorded_locator(raw_path))

    expected_output_locators = {
        (V2_PACKAGE_RELATIVE / filename).as_posix() for filename in V2_OUTPUT_FILENAMES
    }
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != expected_output_locators:
        errors.append("output_inventory_not_exact")
    if isinstance(outputs, dict):
        for raw_path, metadata in outputs.items():
            output_path = resolve_recorded_path(str(raw_path))
            if output_path is None:
                errors.append("unsafe_output_path")
            if not isinstance(metadata, dict) or set(metadata) != {"sha256", "bytes"}:
                errors.append("output_metadata_invalid")
                metadata = {}
            expected_hash = str(metadata.get("sha256") or "")
            expected_bytes = metadata.get("bytes")
            if (
                output_path is None
                or not output_path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or (output_path.is_file() and output_path.stat().st_size != expected_bytes)
                or (output_path.is_file() and sha256_file(output_path) != expected_hash)
            ):
                identity_mismatches["release"].append(public_recorded_locator(str(raw_path)))

    attestation_path = package_dir / V2_ATTESTATION_PATH.name
    attestation = read_object(attestation_path, "validation_attestation")
    expected_attestation_keys = {
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
    if set(attestation) != expected_attestation_keys:
        errors.append("validation_attestation_schema_invalid")
    output_inventory_hash = hashlib.sha256(
        json.dumps(outputs or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_report_hash = None
    if receipt_path is not None and receipt_path.is_file():
        expected_report_hash = v2_versionable_validation_report_sha256(
            manifest,
            receipt,
            manifest_path=path,
            receipt_path=receipt_path,
        )
    if (
        attestation.get("schema_version") != 1
        or attestation.get("evaluation_id") != "peer-review-remediation-v2"
        or attestation.get("status") != "completed_package_validated"
        or not str(attestation.get("validated_at") or "")
        or attestation.get("manifest_path") != expected_manifest_locator
        or attestation.get("manifest_sha256") != sha256_file(path)
        or attestation.get("freeze_receipt_sha256") != manifest.get("freeze_receipt_sha256")
        or attestation.get("versionable_output_inventory_sha256") != output_inventory_hash
        or attestation.get("validation_report_sha256") != expected_report_hash
        or attestation.get("restricted_raw_files_required_for_this_validation") is not True
        or attestation.get("rights_sensitive_raw_text_in_versionable_package") is not False
    ):
        errors.append("validation_attestation_invalid")

    evaluation_commit = str(manifest.get("evaluation_source_commit") or "")
    runtime_commit = (
        (manifest.get("runtime_provenance_validation") or {}).get("code_identity") or {}
    ).get("git_commit")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", evaluation_commit)
        or evaluation_commit != receipt.get("evaluation_source_commit")
        or evaluation_commit != (receipt.get("git") or {}).get("head")
        or evaluation_commit != runtime_commit
        or evaluation_commit != attestation.get("evaluation_source_commit")
    ):
        errors.append("evaluation_commit_agreement_invalid")
    validator_identity = receipt.get("locked_validator_identity")
    if (
        not isinstance(validator_identity, dict)
        or manifest.get("locked_validator_identity") != validator_identity
        or attestation.get("locked_validator_identity") != validator_identity
    ):
        errors.append("locked_validator_identity_disagreement")
    else:
        for locator_key, hash_key in (
            ("lock_path", "lock_sha256"),
            ("validator_path", "validator_sha256"),
            ("runner_path", "runner_sha256"),
        ):
            recorded = resolve_recorded_path(str(validator_identity.get(locator_key) or ""))
            expected_hash = str(validator_identity.get(hash_key) or "")
            if (
                recorded is None
                or not recorded.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                or sha256_file(recorded) != expected_hash
            ):
                errors.append(f"locked_validator_identity_invalid:{locator_key}")
    if manifest.get("frozen_dataset_identity") != receipt.get("frozen_dataset_identity"):
        errors.append("frozen_dataset_identity_disagreement")

    checks = {
        category: "match" if not mismatches else "mismatch"
        for category, mismatches in identity_mismatches.items()
    }
    checks["manifest"] = "match" if not errors else "invalid"
    status = (
        "invalid"
        if errors
        else "current"
        if all(value == "match" for value in checks.values())
        else "stale"
    )
    return {
        "status": status,
        "path": repository_logical_path(path),
        "checks": checks,
        "identity_mismatches": identity_mismatches,
        "errors": errors,
        "freshness_contract": "strict_completed_attested_package_v2",
        "package_inventory_exact": observed_names == V2_PACKAGE_FILENAMES,
        "restricted_raw_validation": {
            "status": "recorded_attestation_only",
            "independently_rechecked_by_dashboard": False,
        },
        "head_commit_compared": False,
        "docs_only_commits_affect_freshness": False,
    }


def recursive_value(payload: Any, candidate_keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in candidate_keys and isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = recursive_value(value, candidate_keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = recursive_value(value, candidate_keys)
            if found:
                return found
    return None


def parse_current_review(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_artifact_results(path)
    payload = result["payload"]
    counts = payload["counts"]
    return {
        **base_status(path, "available"),
        "case_count": counts["total"],
        "artifact_count": counts["by_item_type"]["paper_artifact"],
        "citation_coverage": None,
        "warnings_count": 0,
        "sections_with_explicit_support": 0,
        "sections_inferred": 0,
        "sections_not_found": 0,
        "ai_reviewed_count": counts["by_target_status"]["ai_reviewed"],
        "needs_reprocess_count": counts["by_target_status"]["needs_reprocess"],
        "review_event_count": counts["total"],
        "citation_evidence_locator_count": counts["citation_evidence_locator_count"],
        "reviewer_type": payload["reviewer_type"],
        "review_notice": payload["review_notice"],
        "grounding_counts": empty_grounding_counts(),
    }


def parse_retrieval_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "question_count": 0,
            "recall_at_3": None,
            "recall_at_5": None,
            "mrr": None,
        }
    payload = result["payload"]
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "question_count": metrics.get("question_count", len(payload.get("questions", []))),
        "recall_at_3": metrics.get("recall_at_3"),
        "recall_at_5": metrics.get("recall_at_5"),
        "mrr": metrics.get("mrr"),
        "mode": payload.get("mode"),
        "top_k": payload.get("top_k"),
        "warnings_count": len(payload.get("warnings", []) or []),
    }


def parse_qa_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "question_count": 0,
            "answer_count": 0,
            "cited_gold_paper_count": 0,
            "citation_count": 0,
            "grounding_counts": empty_grounding_counts(),
        }
    payload = result["payload"]
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    return {
        **base_status(path, "available"),
        "question_count": payload.get("question_count", len(rows)),
        "answer_count": len(rows),
        "cited_gold_paper_count": sum(1 for row in rows if row.get("any_gold_paper_cited")),
        "citation_count": sum(int(row.get("citation_count") or 0) for row in rows),
        "grounding_counts": count_values(rows, "grounding_status", empty_grounding_counts()),
        "mode": payload.get("mode"),
        "top_k": payload.get("top_k"),
    }


def parse_extension_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "case_count": 0,
            "recommendation_count": 0,
            "citation_coverage": None,
            "grounding_counts": empty_grounding_counts(),
            "warnings_count": 0,
        }
    payload = result["payload"]
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "case_count": payload.get("case_count", len(cases)),
        "recommendation_count": sum(int(case.get("recommendation_count") or 0) for case in cases),
        "citation_coverage": metrics.get("average_citation_coverage"),
        "grounding_counts": {
            "grounded": metrics.get("grounded_cases", 0),
            "partial": metrics.get("partial_cases", 0),
            "unsupported": metrics.get("unsupported_cases", 0),
        },
        "warnings_count": sum(int(case.get("warnings_count") or 0) for case in cases),
    }


def parse_artifact_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "case_count": 0,
            "artifact_count": 0,
            "citation_coverage": None,
            "grounding_counts": empty_grounding_counts(),
            "warnings_count": 0,
            "sections_with_explicit_support": 0,
            "sections_inferred": 0,
            "sections_not_found": 0,
        }
    payload = result["payload"]
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "case_count": payload.get("case_count", len(cases)),
        "artifact_count": sum(int(case.get("artifact_count") or 0) for case in cases),
        "citation_coverage": metrics.get("average_citation_coverage"),
        "grounding_counts": {
            "grounded": metrics.get("grounded_cases", 0),
            "partial": metrics.get("partial_cases", 0),
            "unsupported": metrics.get("unsupported_cases", 0),
        },
        "warnings_count": sum(int(case.get("warnings_count") or 0) for case in cases),
        "sections_with_explicit_support": sum(int(case.get("sections_with_explicit_support") or 0) for case in cases),
        "sections_inferred": sum(int(case.get("sections_inferred") or 0) for case in cases),
        "sections_not_found": sum(int(case.get("sections_not_found") or 0) for case in cases),
    }


def read_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "not_run"}
    try:
        return {"status": "available", "payload": json.loads(path.read_text(encoding="utf-8"))}
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "error": str(exc)}


def base_status(path: Path, status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "result_file_exists": path.exists(),
        "path": repository_logical_path(path),
        "last_run_timestamp": file_timestamp(path),
        **({"error": error} if error else {}),
    }


def template_availability(evaluation_dir: Path) -> dict[str, bool]:
    return {
        "retrieval_questions": (evaluation_dir / "questions.jsonl").exists()
        or (evaluation_dir / "questions.sample.jsonl").exists(),
        "qa_questions": (evaluation_dir / "qa_questions.jsonl").exists()
        or (evaluation_dir / "qa_questions.sample.jsonl").exists(),
        "extension_human_review_template": (evaluation_dir / "extension_human_review_template.csv").exists(),
        "artifact_human_review_template": (evaluation_dir / "artifact_human_review_template.csv").exists(),
    }


def overall_quality(session: Session) -> dict[str, Any]:
    return {
        "eligible_indexed_chunks": session.exec(
            select(func.count())
            .select_from(Chunk)
            .join(Paper, Paper.paper_id == Chunk.paper_id)
            .where(Paper.corpus_eligibility_status == "eligible")
        ).one(),
        "eligible_searchable_papers": session.exec(
            select(func.count(func.distinct(Chunk.paper_id)))
            .select_from(Chunk)
            .join(Paper, Paper.paper_id == Chunk.paper_id)
            .where(Paper.corpus_eligibility_status == "eligible")
        ).one(),
        "generated_artifacts": session.exec(select(func.count()).select_from(PaperArtifact)).one(),
        "artifacts_needing_review": session.exec(
            select(func.count()).select_from(PaperArtifact).where(PaperArtifact.review_status == "needs_review")
        ).one(),
        "recommendations_needing_review": session.exec(
            select(func.count())
            .select_from(ThesisRecommendation)
            .where(ThesisRecommendation.review_status == "needs_review")
        ).one(),
        "answers_needing_review": session.exec(
            select(func.count()).select_from(RAGAnswer).where(RAGAnswer.review_status == "needs_review")
        ).one(),
        "answers_needing_reprocess": session.exec(
            select(func.count()).select_from(RAGAnswer).where(RAGAnswer.review_status == "needs_reprocess")
        ).one(),
        "ai_reviewed_artifacts": session.exec(
            select(func.count()).select_from(PaperArtifact).where(PaperArtifact.review_status == "ai_reviewed")
        ).one(),
        "ai_reviewed_recommendations": session.exec(
            select(func.count())
            .select_from(ThesisRecommendation)
            .where(ThesisRecommendation.review_status == "ai_reviewed")
        ).one(),
        "papers_needing_review": session.exec(
            select(func.count()).select_from(Paper).where(Paper.review_status == "needs_review")
        ).one(),
        "total_review_events": session.exec(select(func.count()).select_from(ReviewEvent)).one(),
    }


def count_values(rows: list[dict[str, Any]], key: str, defaults: dict[str, int]) -> dict[str, int]:
    counts = dict(defaults)
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def empty_grounding_counts() -> dict[str, int]:
    return {"grounded": 0, "partial": 0, "unsupported": 0}


def file_timestamp(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def latest_evaluation_timestamp(evaluation_dir: Path = DEFAULT_EVALUATION_DIR) -> str | None:
    if evaluation_dir == DEFAULT_EVALUATION_DIR:
        paths = list(CURRENT_RESULT_FILES.values())
        timestamps = [datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) for path in paths if path.exists()]
        return max(timestamps).isoformat() if timestamps else None
    timestamps = [
        datetime.fromtimestamp((evaluation_dir / filename).stat().st_mtime, tz=UTC)
        for filename in RESULT_FILES.values()
        if (evaluation_dir / filename).exists()
    ]
    if not timestamps:
        return None
    return max(timestamps).isoformat()


def evaluation_files_present(evaluation_dir: Path = DEFAULT_EVALUATION_DIR) -> dict[str, bool]:
    if evaluation_dir == DEFAULT_EVALUATION_DIR:
        return {key: path.exists() for key, path in CURRENT_RESULT_FILES.items()}
    return {key: (evaluation_dir / filename).exists() for key, filename in RESULT_FILES.items()}
