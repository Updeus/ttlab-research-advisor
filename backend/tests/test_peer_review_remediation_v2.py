from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import re
import shutil

import fitz
import pytest

from app.evaluation import dashboard as dashboard_module
from app.reproducibility.release import CANONICAL_V2_RELEASE_FILES, should_include


ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = ROOT / "data" / "evaluation"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dashboard_v2_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Path]]:
    canonical = Path("artifacts/peer_review_remediation/v2")
    package = tmp_path / canonical
    package.mkdir(parents=True)
    code_path = tmp_path / "backend/app/example.py"
    lock_path = tmp_path / "backend/requirements-lock.txt"
    validator_path = tmp_path / "data/evaluation/validate_peer_review_remediation_v2.py"
    runner_path = tmp_path / "data/evaluation/run_peer_review_remediation_v2.py"
    database_path = tmp_path / "data/papers.db"
    for path, value in (
        (code_path, "print('frozen')\n"),
        (lock_path, "safe==1.0\n"),
        (validator_path, "# frozen validator\n"),
        (runner_path, "# frozen runner\n"),
        (database_path, "frozen database bytes"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    outputs = {filename: package / filename for filename in dashboard_module.V2_OUTPUT_FILENAMES}
    for filename, path in outputs.items():
        if filename == "qa_metrics_v2.json":
            value = {"by_split": {"test": {"source": "qa"}}}
        elif filename == "finder_metrics_v2.json":
            value = {"by_split": {"test": {"source": "finder"}}}
        elif filename == "topic_metrics_v2.json":
            value = {"by_split": {"test": {"source": "topics"}}}
        elif filename == "ocr_fixture_results_v2.json":
            value = {"status": "pass"}
        elif path.suffix == ".jsonl":
            path.write_text("", encoding="utf-8")
            continue
        elif path.suffix == ".tex":
            path.write_text("% generated\n", encoding="utf-8")
            continue
        else:
            value = {}
        path.write_text(json.dumps(value), encoding="utf-8")
    commit = "a" * 40
    locked_identity = {
        "status": "locked_environment_valid",
        "python_version": "3.12.0",
        "lock_path": "backend/requirements-lock.txt",
        "lock_sha256": _sha256(lock_path),
        "locked_package_count": 1,
        "validator_path": "data/evaluation/validate_peer_review_remediation_v2.py",
        "validator_sha256": _sha256(validator_path),
        "runner_path": "data/evaluation/run_peer_review_remediation_v2.py",
        "runner_sha256": _sha256(runner_path),
    }
    frozen_files = {
        path.relative_to(tmp_path).as_posix(): {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in (code_path, lock_path, validator_path, runner_path, database_path)
    }
    frozen_dataset_identity = {"ask": {}, "finder": {}, "topics": {}}
    receipt_path = package / "freeze_receipt_v2.json"
    receipt = {
        "evaluation_source_commit": commit,
        "git": {"head": commit, "evaluation_sources_clean_and_committed": True},
        "files": frozen_files,
        "frozen_dataset_identity": frozen_dataset_identity,
        "locked_validator_identity": locked_identity,
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    output_inventory = {
        (canonical / filename).as_posix(): {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for filename, path in outputs.items()
    }
    manifest_path = package / "manifest_v2.json"
    manifest = {
        "evaluation_id": "peer-review-remediation-v2",
        "status": "completed",
        "reviewer": {"reviewer_type": "ai", "human_review": False},
        "human_validation_claimed": False,
        "entailment_claimed": False,
        "public_validation_claimed": False,
        "technical_scope_only": True,
        "public_projection_exercised": False,
        "v1_artifacts_overwritten": False,
        "tracked_database_mutated": False,
        "release_contains_rights_sensitive_raw_text": False,
        "technical_selection_predicate": "technical predicate",
        "public_selection_predicate_recorded_not_tested": "public predicate",
        "provider_environment_overrides": {
            "TTLAB_ALLOWED_LLM_PROVIDERS": '["offline_extractive"]',
            "TTLAB_DEFAULT_LLM_PROVIDER": "offline_extractive",
        },
        "restricted_raw_outputs": {
            "required": True,
            "retained_locally": True,
            "committed": False,
            "release_included": False,
            "lawful_local_corpus_access_required_for_exact_reproduction": True,
        },
        "freeze_receipt": (canonical / receipt_path.name).as_posix(),
        "freeze_receipt_sha256": _sha256(receipt_path),
        "evaluation_source_commit": commit,
        "frozen_dataset_identity": frozen_dataset_identity,
        "locked_validator_identity": locked_identity,
        "runtime_provenance_validation": {"code_identity": {"git_commit": commit}},
        "outputs": output_inventory,
        "claim_boundary": "AI-silver technical evaluation only.",
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    attestation_path = package / "validation_attestation_v2.json"
    attestation = {
        "schema_version": 1,
        "evaluation_id": "peer-review-remediation-v2",
        "status": "completed_package_validated",
        "validated_at": "2026-07-20T00:00:00+00:00",
        "evaluation_source_commit": commit,
        "manifest_path": (canonical / manifest_path.name).as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "freeze_receipt_sha256": _sha256(receipt_path),
        "versionable_output_inventory_sha256": hashlib.sha256(
            json.dumps(output_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "validation_report_sha256": dashboard_module.v2_versionable_validation_report_sha256(
            manifest,
            receipt,
            manifest_path=manifest_path,
            receipt_path=receipt_path,
        ),
        "locked_validator_identity": locked_identity,
        "restricted_raw_files_required_for_this_validation": True,
        "rights_sensitive_raw_text_in_versionable_package": False,
        "claim_boundary": "strict bounded validation",
    }
    attestation_path.write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(dashboard_module, "ROOT", tmp_path)
    monkeypatch.setattr(dashboard_module, "V2_PACKAGE_DIR", package)
    monkeypatch.setattr(dashboard_module, "V2_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(dashboard_module, "V2_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(dashboard_module, "V2_ATTESTATION_PATH", attestation_path)
    monkeypatch.setattr(
        dashboard_module,
        "V2_RESULT_FILES",
        {
            "qa": outputs["qa_metrics_v2.json"],
            "finder": outputs["finder_metrics_v2.json"],
            "topics": outputs["topic_metrics_v2.json"],
            "ocr": outputs["ocr_fixture_results_v2.json"],
        },
    )
    return manifest_path, outputs


def test_v2_canonical_package_path_is_consistent_across_integration_layers() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_path_contract_v2")
    protocol = json.loads(
        (EVALUATION_DIR / "peer_review_remediation_v2_protocol.json").read_text(encoding="utf-8")
    )
    canonical = Path("artifacts/peer_review_remediation/v2")
    reproduce_script = (ROOT / "scripts" / "reproduce_all.sh").read_text(encoding="utf-8")
    reproducibility_doc = (ROOT / "docs" / "REPRODUCIBILITY.md").read_text(encoding="utf-8")

    assert runner.CANONICAL_OUT_RELATIVE == canonical
    assert runner.CANONICAL_OUT_DIR == ROOT / canonical
    assert dashboard_module.V2_PACKAGE_RELATIVE == canonical
    assert dashboard_module.V2_PACKAGE_DIR == ROOT / canonical
    assert protocol["output_contract"]["canonical_directory"] == canonical.as_posix()
    assert CANONICAL_V2_RELEASE_FILES == {
        runner.RECEIPT_PATH.name,
        runner.VALIDATION_ATTESTATION_PATH.name,
        *(path.name for path in runner.OUTPUT_PATHS.values()),
    }
    assert f'export TTLAB_V2_ARTIFACT_DIR="$RUN_ROOT/{canonical.as_posix()}"' in reproduce_script
    assert canonical.as_posix() in reproducibility_doc
    assert should_include(canonical / "manifest_v2.json") == (True, None)
    assert should_include(
        Path("artifacts/reproduction/peer_review_remediation/v2/manifest_v2.json")
    ) == (False, "noncanonical_v2_artifact_path")


def test_full_reproduction_stages_static_inputs_then_resets_before_evaluation() -> None:
    reproduce_script = (ROOT / "scripts" / "reproduce_all.sh").read_text(encoding="utf-8")

    stage_call = reproduce_script.index("  stage_full_test_fixture\n")
    backend_tests = reproduce_script.index('run_in_source backend-tests "$PYTHON" -m pytest')
    reset_call = reproduce_script.index("  reset_full_runtime_fixture\n")
    fresh_snapshot = reproduce_script.index("  run_in_source database-snapshot", reset_call)
    v2_prepare = reproduce_script.index("  run_in_source remediation-v2-prepare", fresh_snapshot)

    assert stage_call < backend_tests < reset_call < fresh_snapshot < v2_prepare
    assert "for fixture_directory in pdfs extracted_text chunks indexes" in reproduce_script
    assert "full_test_database_snapshot.json" in reproduce_script
    assert "full_test_runtime_after_tests" in reproduce_script
    assert "find \"$generated_path\" -mindepth 1 ! -name '.gitkeep' -delete" in reproduce_script

    frontend_runner = (ROOT / "frontend" / "scripts" / "run-vitest.mjs").read_text(encoding="utf-8")
    assert '"--maxWorkers", "1", "--no-file-parallelism"' in frontend_runner


def test_manuscript_capture_isolation_and_v2_identity_contracts_fail_closed() -> None:
    capture = (ROOT / "thesis/scripts/capture_interface_screenshots.mjs").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend/src/pages/AdminReviewPage.tsx").read_text(encoding="utf-8")

    for required in (
        "TTLAB_SCREENSHOT_RUNTIME_ROOT",
        "TTLAB_SCREENSHOT_SOURCE_DB_SHA256",
        "TTLAB_SCREENSHOT_SOURCE_DB_FAMILY_SHA256",
        "TTLAB_SCREENSHOT_RUNTIME_DB_PATH",
        "TTLAB_SCREENSHOT_DATABASE_SNAPSHOT_EVIDENCE",
        "TTLAB_SCREENSHOT_RUNTIME_INDEX_DIR",
        "sqlite3.Connection.backup",
        "runtime_database_distinct_inode",
        "source_database_family_sha256_after_capture",
        "observed_source_assets_unchanged_during_script",
        'capabilities.actor?.role === "reviewer"',
        'capabilities.capabilities?.set_publication_and_rights === false',
        'capabilities.capabilities?.trigger_ingestion === false',
        'freshness?.freshness_contract === "strict_completed_attested_package_v2"',
        'evidence?.status === "current"',
        'evidence?.package_status === "completed"',
        "report.promotable = true",
    ):
        assert required in capture
    assert 'capabilities.actor?.role === "admin"' not in capture
    assert 'data-admin-governance-capture="aggregate-summary"' in admin_page
    assert capture.index("verifySourceAssetsUnchanged") < capture.index('report.status = "pass"')


def test_v2_dashboard_reads_metrics_from_the_canonical_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = Path("artifacts/peer_review_remediation/v2")
    _manifest_path, _outputs = build_dashboard_v2_package(tmp_path, monkeypatch)

    result = dashboard_module.parse_v2_evidence_package()

    assert result["status"] == "current"
    assert result["package_status"] == "completed"
    assert result["reviewer_type"] == "ai"
    assert result["human_validation"] is False
    assert result["qa_test"] == {"source": "qa"}
    assert result["finder_test"] == {"source": "finder"}
    assert result["topics_test"] == {"source": "topics"}
    assert result["ocr"] == {"status": "pass"}
    assert result["manifest_path"] == (canonical / "manifest_v2.json").as_posix()
    assert result["freshness"]["freshness_contract"] == "strict_completed_attested_package_v2"
    docs = tmp_path / "docs/later-note.md"
    docs.parent.mkdir(parents=True)
    docs.write_text("later docs-only change\n", encoding="utf-8")
    assert dashboard_module.v2_package_freshness()["status"] == "current"


def test_v2_dashboard_rejects_arbitrary_attestation_report_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dashboard_v2_package(tmp_path, monkeypatch)
    attestation = json.loads(
        dashboard_module.V2_ATTESTATION_PATH.read_text(encoding="utf-8")
    )
    attestation["validation_report_sha256"] = "b" * 64
    dashboard_module.V2_ATTESTATION_PATH.write_text(
        json.dumps(attestation, sort_keys=True),
        encoding="utf-8",
    )

    result = dashboard_module.v2_package_freshness()

    assert result["status"] == "invalid"
    assert "validation_attestation_invalid" in result["errors"]


@pytest.mark.parametrize("entry_kind", ["directory", "file_symlink"])
def test_v2_dashboard_rejects_nested_and_symlink_package_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_kind: str,
) -> None:
    build_dashboard_v2_package(tmp_path, monkeypatch)
    entry = dashboard_module.V2_PACKAGE_DIR / "unexpected"
    if entry_kind == "directory":
        entry.mkdir()
        (entry / "nested.json").write_text("{}\n", encoding="utf-8")
    else:
        entry.symlink_to(dashboard_module.V2_MANIFEST_PATH)

    result = dashboard_module.v2_package_freshness()

    assert result["status"] == "invalid"
    assert any(error.startswith("package_non_regular_or_nested_entry:") for error in result["errors"])


def test_v2_dashboard_rejects_unexpected_regular_package_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dashboard_v2_package(tmp_path, monkeypatch)
    (dashboard_module.V2_PACKAGE_DIR / "unexpected.json").write_text(
        "{}\n", encoding="utf-8"
    )

    result = dashboard_module.v2_package_freshness()

    assert result["status"] == "invalid"
    assert "package_filename_inventory_mismatch" in result["errors"]


def test_v2_dashboard_never_exposes_absolute_operator_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = Path("artifacts/peer_review_remediation/v2")
    package = tmp_path / canonical
    package.mkdir(parents=True)
    manifest_path = package / "manifest_v2.json"
    outside_receipt = tmp_path.parent / "operator-private" / "freeze.json"
    outside_output = tmp_path.parent / "operator-private" / "answer.json"
    manifest_path.write_text(
        json.dumps(
            {
                "evaluation_id": "peer-review-remediation-v2",
                "status": "completed",
                "freeze_receipt": outside_receipt.as_posix(),
                "freeze_receipt_sha256": "a" * 64,
                "outputs": {outside_output.as_posix(): {"sha256": "b" * 64}},
            }
        ),
        encoding="utf-8",
    )
    missing_manifest = package / "missing-manifest-v2.json"

    monkeypatch.setattr(dashboard_module, "ROOT", tmp_path)
    invalid = dashboard_module.v2_package_freshness(manifest_path)
    not_run = dashboard_module.v2_package_freshness(missing_manifest)
    generic = dashboard_module.base_status(outside_output, "not_run")
    serialized = json.dumps({"invalid": invalid, "not_run": not_run, "generic": generic})

    assert invalid["path"] == (canonical / "manifest_v2.json").as_posix()
    assert not_run["path"] == (canonical / "missing-manifest-v2.json").as_posix()
    assert invalid["identity_mismatches"]["release"] == ["unsafe_repository_path"]
    assert generic["path"] == "answer.json"
    assert tmp_path.as_posix() not in serialized
    assert tmp_path.parent.as_posix() not in serialized
    assert outside_receipt.as_posix() not in serialized
    assert outside_output.as_posix() not in serialized


def test_v2_dashboard_is_selected_even_when_every_v1_artifact_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dashboard_v2_package(tmp_path, monkeypatch)
    missing_v1 = {name: tmp_path / f"missing-{name}.json" for name in dashboard_module.CURRENT_RESULT_FILES}
    monkeypatch.setattr(dashboard_module, "CURRENT_RESULT_FILES", missing_v1)
    monkeypatch.setattr(dashboard_module, "RETRIEVAL_SILVER_PATH", tmp_path / "missing-silver.jsonl")
    monkeypatch.setattr(
        dashboard_module,
        "build_current_evaluation_dashboard",
        lambda _session: {"selected": "v2"},
    )

    assert dashboard_module.build_evaluation_dashboard(object()) == {"selected": "v2"}


def load_module(filename: str, name: str):
    path = EVALUATION_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_protocol_is_source_first_and_splits_are_frozen() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_runner_v2")
    frozen = runner.validate_static_protocol()

    assert len(frozen["ask"]) == 18
    assert len(frozen["finder"]) == 10
    assert len(frozen["topics"]) == 12
    runner.validate_sqlite_source_locators()

    qa_cases = runner.read_jsonl(runner.QA_PATH)
    negatives = [row for row in qa_cases if not row["expected_answerable"]]
    assert len(negatives) == 6
    assert all(row["category"] == "in_domain_absence_probe" for row in negatives)
    assert all(row["negative_evidence"]["context_locator"] for row in negatives)
    finder_cases = runner.read_jsonl(runner.FINDER_PATH)
    assert [row["profile_id"] for row in finder_cases if row["split"] == "sensitivity"] == [
        "finder-v2-t02"
    ]
    assert len([row for row in finder_cases if row["split"] == "test"]) == 5


def test_v2_protocol_retains_ai_silver_claim_boundary() -> None:
    validator = load_module("validate_peer_review_remediation_v2.py", "peer_review_validator_v2")
    report = validator.validate_static()
    protocol = json.loads((EVALUATION_DIR / "peer_review_remediation_v2_protocol.json").read_text(encoding="utf-8"))

    assert report["status"] == "pass"
    assert protocol["reviewer"]["reviewer_type"] == "ai"
    assert protocol["reviewer"]["human_review"] is False
    assert protocol["ask"]["fixed_answerability_rule"]["tuning_on_v2"] is False
    assert protocol["corpus_and_projection_boundary"]["public_projection_evaluated"] is False
    assert protocol["ask"]["temporary_index_preparation"]["rebuild_keyword_index"] is True
    assert protocol["ask"]["provider_environment"]["allowed_llm_providers"] == ["offline_extractive"]
    assert protocol["ask"]["model_when_invoked"] == "sentence-overlap-v1"
    assert protocol["finder"]["provider"] == "offline_deterministic"
    assert protocol["finder"]["model"] == "template-recommender-v1"
    assert protocol["output_contract"]["manuscript_macros"] == "manuscript_macros_v2.tex"
    assert protocol["output_contract"]["validation_attestation"] == "validation_attestation_v2.json"
    assert protocol["output_contract"]["release_filename_policy"] == "exact_allowlist_only"
    assert protocol["output_contract"]["hand_entered_manuscript_metrics_permitted"] is False
    assert protocol["ocr"]["execution_path"].endswith(
        "extract_pdf_text with run_ocr=true and a TesseractOCRProvider"
    )
    assert protocol["historical_v1"]["classification"] == "historical_post_selection_descriptive"
    assert protocol["bootstrap"]["method"] == "cluster_level_percentile_bootstrap"
    assert protocol["corpus_and_projection_boundary"]["generation_link_reconciliation"][
        "legacy_or_mismatched_artifacts"
    ] == "quarantine_fail_closed"
    assert protocol["output_contract"]["restricted_raw_output_policy"][
        "commit_or_release_permitted"
    ] is False


def test_v2_freeze_inventory_covers_backend_runtime_tree() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_freeze_inventory_v2")
    backend_python = set((ROOT / "backend" / "app").rglob("*.py"))

    assert backend_python
    assert backend_python.issubset(set(runner.CODE_PATHS))
    assert runner.QA_PATH not in runner.CODE_PATHS
    assert runner.EVALUATION_ENVIRONMENT == {
        "TTLAB_ALLOWED_LLM_PROVIDERS": '["offline_extractive"]',
        "TTLAB_DEFAULT_LLM_PROVIDER": "offline_extractive",
    }
    runner.validate_output_separation()
    generation_inputs = set(runner.generation_artifact_paths())
    assert generation_inputs
    assert generation_inputs.issubset(set(runner.frozen_input_paths()))
    assert any(path.parent.name == "extracted_text" for path in generation_inputs)
    assert any(path.parent.name == "chunks" for path in generation_inputs)


def test_v2_qa_completeness_counts_only_returned_supporting_citations() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_qa_completeness_v2")
    case = {
        "case_id": "qa-unit",
        "split": "test",
        "expected_answerable": True,
        "gold_locator": {"paper_id": "paper-1", "chunk_id": "chunk-gold"},
        "answer_points": [],
    }
    output = {
        "provider": "offline_extractive",
        "grounding_status": "grounded",
        "answer": "bounded answer",
        "citations": [
            {"paper_id": "paper-1", "chunk_id": "chunk-gold"},
            {"paper_id": "paper-2", "chunk_id": "chunk-pruned"},
        ],
        "claim_support": [
            {
                "claim": "supported",
                "cited_chunk_ids": ["chunk-gold"],
                "supporting_chunk_ids": ["chunk-gold"],
            },
            {
                "claim": "unsupported despite marker",
                "cited_chunk_ids": ["chunk-pruned"],
                "supporting_chunk_ids": [],
            },
        ],
    }

    reviewed = runner.review_qa_case(case, output, "pass_1", 1)
    aggregate = runner.aggregate_qa([reviewed])

    assert reviewed["structurally_cited_claim_count"] == 1
    assert reviewed["used_returned_citation_count"] == 1
    assert aggregate["metrics"]["citation_completeness"] == 0.5


def test_v2_cluster_bootstrap_resamples_declared_clusters() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_cluster_bootstrap_v2")
    runner.BOOTSTRAP_REPLICATES = 40
    rows = [
        {"cluster_id": "paper-a", "value": 0.0},
        {"cluster_id": "paper-a", "value": 1.0},
        {"cluster_id": "paper-b", "value": 1.0},
    ]

    def aggregate(sample):
        return {"metrics": {"mean": sum(row["value"] for row in sample) / len(sample)}}

    result = runner.bootstrap_metrics(
        rows,
        aggregate,
        cluster_key="cluster_id",
        unit="named_source_paper",
    )

    assert result["method"] == "cluster_level_percentile_bootstrap"
    assert result["cluster_count"] == 2
    assert result["unit"] == "named_source_paper"


def test_v2_manuscript_macros_bind_intervals_and_run_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_macro_contract_v2")

    def intervals(*names: str) -> dict[str, dict[str, float | int]]:
        return {
            name: {
                "estimate": 0.5,
                "ci_lower": 0.25,
                "ci_upper": 0.75,
                "valid_replicates": 40,
            }
            for name in names
        }

    artifacts = {
        "qa_metrics": {
            "status": "completed",
            "by_split": {
                "test": {
                    "case_count": 12,
                    "metrics": {
                        "answerability_precision": 0.5,
                        "answerability_recall": 0.5,
                        "false_positive_rate": 0.5,
                        "abstention_rate": 0.5,
                        "exact_gold_locator_citation_precision": 0.5,
                        "citation_completeness": 0.5,
                        "answer_point_coverage": 0.5,
                    },
                }
            },
            "test_bootstrap_95_ci": {
                "metrics": intervals(
                    "answerability_precision",
                    "answerability_recall",
                    "false_positive_rate",
                    "abstention_rate",
                    "exact_gold_locator_citation_precision",
                    "citation_completeness",
                    "answer_point_coverage",
                )
            },
        },
        "finder_metrics": {
            "status": "completed",
            "by_split": {
                "test": {
                    "profile_count": 5,
                    "metrics": {
                        "evidence_only_hit_at_3": 0.4,
                        "full_finder_hit_at_3": 0.6,
                        "paired_hit_at_3_delta": 0.2,
                        "evidence_only_mrr": 0.3,
                        "full_finder_mrr": 0.5,
                        "paired_mrr_delta": 0.2,
                        "candidate_specific_template_conformance_rate": 1.0,
                        "source_fact_suggestion_separation_rate": 1.0,
                        "unknown_implementation_time_retention_rate": 1.0,
                        "full_profile_constraint_contract_fidelity_rate": 1.0,
                    },
                }
            },
            "test_bootstrap_95_ci": {
                "metrics": intervals(
                    "evidence_only_hit_at_3",
                    "full_finder_hit_at_3",
                    "paired_hit_at_3_delta",
                    "evidence_only_mrr",
                    "full_finder_mrr",
                    "paired_mrr_delta",
                )
            },
        },
        "topic_metrics": {
            "status": "completed",
            "by_split": {
                "test": {
                    "case_count": 8,
                    "known_positive_micro": {"recall": 0.5},
                    "known_positive_case_coverage_rate": 0.5,
                    "unadjudicated_predictions": {"count": 4, "share": 0.25},
                }
            },
            "test_bootstrap_95_ci": {
                "metrics": intervals(
                    "known_positive_micro_recall",
                    "known_positive_case_coverage_rate",
                )
            },
        },
        "ocr_results": {
            "status": "completed",
            "provider": {"name": "tesseract", "version": "tesseract 5.3.0"},
            "metrics": {
                "character_error_rate": 0.01,
                "word_error_rate": 0.02,
                "normalized_exact_match": False,
                "repeat_run_text_identical": True,
                "repeat_run_text_artifact_identical": True,
                "repeat_run_configuration_identical": True,
                "repeat_run_sanitized_pipeline_result_identical": True,
            },
        },
    }
    for name, value in artifacts.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        monkeypatch.setitem(runner.OUTPUT_PATHS, name, path)
    receipt = {
        "evaluation_source_commit": "a" * 40,
        "public_projection_evaluated": False,
        "frozen_dataset_identity": {"ask": {"dataset_sha256": "b" * 64}},
        "locked_validator_identity": {"lock_sha256": "c" * 64},
    }
    corpus = {
        "snapshot_id": "snapshot_with_underscore",
        "snapshot_hash": "d" * 64,
        "eligible_paper_count": 23,
        "eligible_chunk_count": 756,
    }
    keyword_index = {
        "rebuild_result": {"completeness_status": "complete"},
        "configuration_sha256": "e" * 64,
    }

    text = runner.manuscript_macro_text(
        receipt=receipt,
        corpus_identity=corpus,
        keyword_index=keyword_index,
    )
    observed = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", text))

    assert observed == set(runner.MANUSCRIPT_MACRO_NAMES)
    assert r"\newcommand{\VTwoQAAnswerabilityPrecisionCi}{[25.0\%, 75.0\%]}" in text
    assert r"\newcommand{\VTwoFinderHitAtThreeDeltaCi}{[+25.0~pp, +75.0~pp]}" in text
    assert r"\newcommand{\VTwoTopicKnownPositiveRecallCi}{[25.0\%, 75.0\%]}" in text
    assert r"\newcommand{\VTwoEvaluationSourceCommitPrefix}{aaaaaaaaaaaa}" in text
    assert r"\newcommand{\VTwoCorpusSnapshotId}{snapshot\_with\_underscore}" in text
    assert "validation_attestation" not in text


def test_v2_manuscript_layout_fallback_never_hides_partial_execution(
    tmp_path: Path,
) -> None:
    helper_spec = importlib.util.spec_from_file_location(
        "manuscript_v2_package_test",
        ROOT / "scripts" / "manuscript_v2_package.py",
    )
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    runner_target = tmp_path / "data" / "evaluation" / "run_peer_review_remediation_v2.py"
    runner_target.parent.mkdir(parents=True)
    shutil.copyfile(EVALUATION_DIR / "run_peer_review_remediation_v2.py", runner_target)

    fallback = helper.load_manuscript_v2_package(tmp_path, allow_not_run=True)
    assert fallback["status"] == "not_run"
    assert fallback["layout_only"] is True
    assert "not experimental evidence" in fallback["macro_text"]

    partial = tmp_path / "artifacts" / "peer_review_remediation" / "v2"
    partial.mkdir(parents=True)
    (partial / "qa_metrics_v2.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="partial remediation-v2 execution"):
        helper.load_manuscript_v2_package(tmp_path, allow_not_run=True)


def test_v2_finder_checks_every_profile_constraint_contract() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_finder_constraints_v2")
    case = {
        "interests": "compare multi-step forecasting approaches for seasonal produce prices",
        "skills": ["Python"],
        "available_time": "2 weeks",
        "project_type": "data analysis",
        "data_constraints": "public data only",
        "preferred_difficulty": "easy",
        "preferred_topics": ["agriculture", "pricing"],
    }
    recommendation = {
        "extension_title": "compare multi-step forecasting approaches for... extension",
        "extension_summary": "Suggested data analysis extension.",
        "why_it_fits_student": "Interests around agriculture, pricing.",
        "required_skills": ["Python", "visualization"],
        "skills_gap": ["visualization"],
        "profile_constraints": {
            "classification": "student_supplied_preferences_not_paper_facts",
            "available_time": "2 weeks",
            "data_constraints": "public data only",
            "preferred_difficulty": "easy",
        },
    }

    checks = runner.finder_profile_constraint_checks(case, recommendation)

    assert checks
    assert all(checks.values())


def test_v2_versionable_projections_remove_rights_sensitive_text() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_projection_v2")
    validator = load_module("validate_peer_review_remediation_v2.py", "peer_review_projection_validator_v2")
    qa = runner.versionable_qa_output(
        {
            "case_id": "qa-unit",
            "split": "test",
            "category": "unit",
            "expected_answerable": True,
            "question": "author-created question",
            "answer": "extractive answer from a paper",
            "citations": [{"chunk_id": "c1", "snippet": "paper excerpt"}],
            "retrieved_chunks": [{"chunk_id": "c1", "snippet": "paper excerpt"}],
            "claim_support": [{"claim": "paper claim", "supporting_chunk_ids": ["c1"]}],
        }
    )
    topic = runner.versionable_topic_output(
        {
            "case_id": "topic-unit",
            "source_locator": {"anchor": "source anchor"},
            "predictions": [
                {"label": "rag", "score": 1.0, "evidence": [{"text": "source excerpt"}]}
            ],
        }
    )
    finder = runner.versionable_finder_output(
        {
            "profile_id": "finder-unit",
            "request": {"interests": "author-created interests"},
            "paired_retrieval": {"result_locators": []},
            "evidence_only": {
                "papers": [
                    {
                        "paper_id": "paper-1",
                        "paper_title": "source title",
                        "authors": ["Source Author"],
                        "passages": [{"chunk_id": "chunk-1", "snippet": "source excerpt"}],
                    }
                ]
            },
            "full_finder": {
                "recommendations": [
                    {
                        "paper_id": "paper-1",
                        "paper_title": "source title",
                        "extension_summary": "generated recommendation",
                        "source_supported_facts": [
                            {"claim": "source claim", "snippet": "source excerpt"}
                        ],
                    }
                ]
            },
        }
    )

    validator.assert_versionable_raw_boundary(qa, "qa")
    validator.assert_versionable_raw_boundary(topic, "topic")
    validator.assert_versionable_raw_boundary(finder, "finder")
    assert qa["answer_attestation"]["sha256"]
    assert topic["predictions"][0]["evidence"][0]["text_attestation"]["sha256"]
    assert finder["full_finder"]["recommendations"][0]["generated_text_attestations"][
        "extension_summary_attestation"
    ]["sha256"]


def test_v2_runtime_provenance_rejects_non_exhaustive_source_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_provenance_v2")
    qa_path = tmp_path / "qa.jsonl"
    finder_path = tmp_path / "finder.jsonl"
    source_hashes = {"chunk-a": "a" * 64}
    provenance = {
        "code_identity": {"scope": "backend/app", "status": "clean_commit"},
        "corpus_identity": {
            "snapshot_id": "snapshot",
            "snapshot_hash": "b" * 64,
            "eligible_chunk_count": 2,
            "eligible_paper_count": 1,
        },
        "source_identity": {
            "chunk_ids": ["chunk-a"],
            "chunk_descriptor_sha256": runner.sha256_bytes(
                runner.canonical_json(source_hashes).encode("utf-8")
            ),
        },
        "retrieval_identity": {
            "mode": "keyword",
            "scope": "technical",
            "indexes": [{"kind": "keyword", "status": "ready", "completeness_status": "complete", "corpus_snapshot_hash": "b" * 64}],
        },
        "generation_identity": {
            "provider": "offline_extractive",
            "model": "sentence-overlap-v1",
            "immutable_model_identity": True,
        },
    }
    runner.write_jsonl(
        qa_path,
        [
            {
                "case_id": "qa-unit",
                "provider": "offline_extractive",
                "model": "sentence-overlap-v1",
                "runtime_provenance": provenance,
                "retrieved_chunks": [
                    {"chunk_id": "chunk-a", "effective_source_sha256": "a" * 64},
                    {"chunk_id": "chunk-b", "effective_source_sha256": "c" * 64},
                ],
            }
        ],
    )
    runner.write_jsonl(finder_path, [])
    monkeypatch.setitem(runner.OUTPUT_PATHS, "qa_raw", qa_path)
    monkeypatch.setitem(runner.OUTPUT_PATHS, "finder_raw", finder_path)

    with pytest.raises(RuntimeError, match="exactly equal"):
        runner.validate_runtime_provenance_outputs(
            provenance["corpus_identity"],
            {"rebuild_result": {"completeness_status": "complete"}},
        )


def test_v2_generation_reconciliation_receipt_is_balanced() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_reconciliation_v2")
    receipt = {
        "attempted": 3,
        "reconciled": 1,
        "already_current": 1,
        "quarantined": 1,
        "reasons": {"missing_chunk_manifest": 1},
        "dry_run": False,
    }

    assert runner.validate_generation_reconciliation(receipt) == receipt
    with pytest.raises(RuntimeError, match="do not balance"):
        runner.validate_generation_reconciliation({**receipt, "quarantined": 2})


def test_v2_topic_metrics_treat_unlisted_predictions_as_unadjudicated() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_topic_scope_v2")
    aggregate = runner.topic_aggregate(
        [
            {
                "case_id": "topic-unit",
                "gold_labels": ["rag"],
                "predicted_labels": ["rag", "information retrieval"],
            }
        ],
        ["information retrieval", "rag"],
    )

    assert aggregate["known_positive_micro"]["recall"] == 1.0
    assert aggregate["unadjudicated_predictions"]["count"] == 1
    assert aggregate["unadjudicated_predictions"]["false_positive_interpretation_permitted"] is False
    assert "precision" not in aggregate
    assert "f1" not in aggregate


def test_v2_validator_rejects_duplicate_ids_and_split_drift() -> None:
    validator = load_module("validate_peer_review_remediation_v2.py", "peer_review_exact_ids_v2")
    expected = [
        {"case_id": "case-a", "split": "dev"},
        {"case_id": "case-b", "split": "test"},
    ]
    with pytest.raises(AssertionError, match="duplicate"):
        validator.validate_exact_ids_and_splits(
            [expected[0], expected[0]], expected, "case_id", "unit"
        )
    with pytest.raises(AssertionError, match="split drift"):
        validator.validate_exact_ids_and_splits(
            [expected[0], {"case_id": "case-b", "split": "dev"}],
            expected,
            "case_id",
            "unit",
        )


@pytest.mark.parametrize("entry_kind", ["directory", "symlink"])
def test_v2_validator_rejects_non_regular_flat_package_entries(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    validator = load_module(
        "validate_peer_review_remediation_v2.py",
        f"peer_review_flat_package_v2_{entry_kind}",
    )
    package = tmp_path / "v2"
    package.mkdir()
    (package / "expected.json").write_text("{}\n", encoding="utf-8")
    entry = package / "unexpected"
    if entry_kind == "directory":
        entry.mkdir()
    else:
        entry.symlink_to(package / "expected.json")

    with pytest.raises(AssertionError, match="non-regular or nested"):
        validator.validate_flat_regular_file_inventory(
            package,
            {"expected.json"},
            "unit package",
        )


def test_v2_validator_rejects_unexpected_regular_flat_package_file(
    tmp_path: Path,
) -> None:
    validator = load_module(
        "validate_peer_review_remediation_v2.py",
        "peer_review_flat_package_v2_regular",
    )
    package = tmp_path / "v2"
    package.mkdir()
    (package / "expected.json").write_text("{}\n", encoding="utf-8")
    (package / "unexpected.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="flat filename inventory drift"):
        validator.validate_flat_regular_file_inventory(
            package,
            {"expected.json"},
            "unit package",
        )


def test_v2_validator_report_digest_is_bound_to_versionable_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = load_module(
        "validate_peer_review_remediation_v2.py",
        "peer_review_bound_report_digest_v2",
    )
    manifest_path = tmp_path / "manifest_v2.json"
    receipt_path = tmp_path / "freeze_receipt_v2.json"
    manifest = {
        "evaluation_source_commit": "a" * 40,
        "outputs": {"artifact.json": {"sha256": "b" * 64, "bytes": 1}},
    }
    receipt = {
        "frozen_dataset_identity": {"ask": {"sha256": "c" * 64}},
        "locked_validator_identity": {"validator_sha256": "d" * 64},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setitem(validator.runner.OUTPUT_PATHS, "manifest", manifest_path)
    monkeypatch.setattr(validator.runner, "RECEIPT_PATH", receipt_path)

    digest = validator.validation_report_sha256(manifest=manifest, receipt=receipt)
    changed = json.loads(json.dumps(manifest))
    changed["outputs"]["artifact.json"]["bytes"] = 2

    assert validator.versionable_validation_report_portion(
        manifest, receipt
    ) == dashboard_module.v2_versionable_validation_report_portion(
        manifest,
        receipt,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
    )
    assert digest != "b" * 64
    assert digest != validator.validation_report_sha256(manifest=changed, receipt=receipt)

    with pytest.raises(AssertionError, match="strict restricted-raw recomputation"):
        validator.write_validation_attestation(
            {
                "status": "pass",
                "restricted_raw_files_checked": False,
                "strict_recomputation": {"status": "not_performed"},
            }
        )


def _strict_recomputation_fixture(validator):
    runner = validator.runner
    runner.BOOTSTRAP_REPLICATES = 20
    chunk_hashes = {
        "chunk-1": {
            "chunk_text_sha256": "a" * 64,
            "effective_source_sha256": "b" * 64,
        }
    }
    citation = {
        "paper_id": "paper-1",
        "title": "Paper One",
        "chunk_id": "chunk-1",
        "page_start": 1,
        "page_end": 1,
        "section": "Results",
        "score": 1.0,
        "snippet": "source evidence",
    }

    qa_cases = [
        {
            "case_id": "qa-unit",
            "split": "test",
            "category": "unit",
            "expected_answerable": True,
            "question": "What did the paper report?",
            "gold_locator": {"paper_id": "paper-1", "chunk_id": "chunk-1"},
            "answer_points": [{"point_id": "p1", "groups": [["reported result"]]}],
        }
    ]
    qa_response = {
        "provider": "offline_extractive",
        "model": "sentence-overlap-v1",
        "grounding_status": "grounded",
        "support_status": "support_unverified",
        "retrieval_mode": "keyword",
        "retrieval_metadata": {"retrieval_scope": "technical"},
        "generation_metadata": {},
        "runtime_provenance": {"generated_at": "2026-07-20T00:00:00+00:00"},
        "answerability": {"answerable": True, "reason": "matched"},
        "answer": "The reported result was positive.",
        "citations": [citation],
        "retrieved_chunks": [{**citation, "text": "source evidence"}],
        "claim_support": [
            {
                "claim": "The reported result was positive.",
                "classification": "supported",
                "cited_chunk_ids": ["chunk-1"],
                "supporting_chunk_ids": ["chunk-1"],
                "citation_support": [],
                "lexical_overlap": 1.0,
                "entailment_verified": False,
            }
        ],
        "warnings": [],
        "unsupported_claims": [],
    }
    qa_review = runner.sanitize_qa_response(qa_cases[0], qa_response, chunk_hashes)
    qa_pass1 = runner.shuffled_review(
        qa_cases, {"qa-unit": qa_review}, "pass_1", runner.review_qa_case
    )
    qa_pass2 = runner.shuffled_review(
        qa_cases, {"qa-unit": qa_review}, "pass_2", runner.review_qa_case
    )
    qa_disagreements = runner.review_disagreements(
        qa_pass1, qa_pass2, validator.QA_REVIEW_FIELDS
    )
    qa_by_split = {
        split: runner.aggregate_qa([row for row in qa_pass1 if row["split"] == split])
        for split in ("dev", "test")
    }
    qa_by_split["all"] = runner.aggregate_qa(qa_pass1)

    finder_cases = [
        {
            "profile_id": "finder-unit",
            "split": "test",
            "constraint_pair": None,
            "gold_paper_id": "paper-1",
            "interests": "rag systems",
            "skills": ["Python"],
            "available_time": "2 weeks",
            "project_type": "data analysis",
            "data_constraints": "public data only",
            "preferred_difficulty": "easy",
            "preferred_topics": ["rag"],
        }
    ]
    retrieval = {
        "expanded_query": "rag systems",
        "mode": "keyword",
        "retrieval_strategy": "keyword",
        "retriever_config": {},
        "warnings": [],
        "results": [{"chunk_id": "chunk-1", "paper_id": "paper-1", "scores": {"keyword": 1.0}}],
    }
    baseline = {
        "output_mode": "evidence_only",
        "retrieval_mode": "keyword",
        "vector_provider": None,
        "top_k": 3,
        "query": "rag systems",
        "expanded_query": "rag systems",
        "papers": [
            {
                "rank": 1,
                "paper_id": "paper-1",
                "paper_title": "Paper One",
                "authors": ["Author"],
                "year": 2025,
                "retrieval_score": 1.0,
                "passages": [citation],
            }
        ],
        "warnings": [],
        "disclaimer": "evidence only",
    }
    recommendation = {
        "rank": 1,
        "paper_id": "paper-1",
        "paper_title": "Paper One",
        "paper_focus": "RAG",
        "authors": ["Author"],
        "year": 2025,
        "fit_score": 1.0,
        "score_breakdown": {},
        "extension_title": "rag systems extension",
        "extension_summary": "Suggested data analysis extension.",
        "why_it_fits_student": "Matches rag.",
        "mvp_scope": "Paper One MVP",
        "stretch_goals": [],
        "required_skills": ["Python"],
        "skills_gap": [],
        "data_required": "public data",
        "evaluation_plan": "Paper One evaluation",
        "difficulty": "easy",
        "risk_level": "low",
        "risk_basis": "bounded",
        "implementation_time": "unknown",
        "profile_constraints": {
            "classification": "student_supplied_preferences_not_paper_facts",
            "available_time": "2 weeks",
            "data_constraints": "public data only",
            "preferred_difficulty": "easy",
        },
        "mvp_scope_basis": {"classification": "system_suggestion"},
        "evaluation_plan_basis": {"classification": "system_suggestion"},
        "implementation_time_basis": {"classification": "unknown", "reason": "not established"},
        "identified_gap": {"text": "inferred gap", "support_status": "inferred_from_paper", "source_chunk_ids": ["chunk-1"]},
        "source_supported_facts": [
            {
                "claim": "source fact",
                "snippet": "source evidence",
                "chunk_id": "chunk-1",
                "support_status": "support_unverified",
                "entailment_verified": False,
            }
        ],
        "data_availability": "public",
        "data_availability_evidence": {"status": "unverified", "classification": "unknown", "source_chunk_ids": [], "matched_terms": []},
        "difficulty_basis": {"value": "easy", "classification": "system_suggestion", "source_chunk_ids": [], "matched_terms": []},
        "related_papers": [],
        "potential_researcher_fit": [],
        "citations": [citation],
        "warnings": [],
    }
    full = {
        "grounding_status": "partial",
        "provider": "offline_deterministic",
        "model": "template-recommender-v1",
        "answerability": {"answerable": True},
        "runtime_provenance": {"generated_at": "2026-07-20T00:00:00+00:00"},
        "recommendations": [recommendation],
        "warnings": [],
    }
    finder_review = runner.sanitize_finder(
        finder_cases[0], retrieval, baseline, full, chunk_hashes
    )
    finder_pass1 = runner.shuffled_review(
        finder_cases,
        {"finder-unit": finder_review},
        "pass_1",
        runner.review_finder_case,
    )
    finder_pass2 = runner.shuffled_review(
        finder_cases,
        {"finder-unit": finder_review},
        "pass_2",
        runner.review_finder_case,
    )
    finder_disagreements = runner.review_disagreements(
        finder_pass1, finder_pass2, validator.FINDER_REVIEW_FIELDS
    )
    finder_by_split = {
        split: runner.aggregate_finder(
            [row for row in finder_pass1 if row["split"] == split]
        )
        for split in ("dev", "test", "sensitivity")
    }
    finder_by_split["primary_dev_and_test"] = runner.aggregate_finder(finder_pass1)
    finder_by_split["all_including_sensitivity"] = runner.aggregate_finder(finder_pass1)

    topic_cases = [{"case_id": "topic-unit", "split": "test"}]
    topic_output = {
        "case_id": "topic-unit",
        "split": "test",
        "cluster_id": "paper-1",
        "paper_id": "paper-1",
        "source_locator": {
            "chunk_id": "chunk-1",
            "paper_id": "paper-1",
            **chunk_hashes["chunk-1"],
            "anchor": "source evidence",
        },
        "gold_labels": ["rag"],
        "predicted_labels": ["rag"],
        "predictions": [
            {"label": "rag", "score": 1.0, "evidence": [{"chunk_id": "chunk-1", "text": "source evidence"}]}
        ],
        "reviewer": runner.REVIEWER,
        "scope": "technical",
    }
    vocabulary = ["rag"]
    topic_by_split = {
        split: runner.topic_aggregate(
            [topic_output] if split == "test" else [], vocabulary
        )
        for split in ("dev", "test")
    }
    topic_by_split["all"] = runner.topic_aggregate([topic_output], vocabulary)

    decoded = {
        "qa_raw": [runner.versionable_qa_output(qa_review)],
        "qa_pass1": qa_pass1,
        "qa_pass2": qa_pass2,
        "qa_disagreements": qa_disagreements,
        "qa_metrics": {
            "by_split": qa_by_split,
            "repeatability": qa_disagreements,
            "test_bootstrap_95_ci": runner.bootstrap_metrics(
                qa_pass1,
                runner.aggregate_qa,
                cluster_key="cluster_id",
                unit="named_source_paper",
            ),
        },
        "finder_raw": [runner.versionable_finder_output(finder_review)],
        "finder_pass1": finder_pass1,
        "finder_pass2": finder_pass2,
        "finder_disagreements": finder_disagreements,
        "finder_metrics": {
            "by_split": finder_by_split,
            "repeatability": finder_disagreements,
            "constraint_variation": validator._finder_constraint_variation(finder_pass1),
            "test_bootstrap_95_ci": runner.bootstrap_metrics(
                finder_pass1,
                runner.aggregate_finder,
                cluster_key="cluster_id",
                unit="profile_family",
            ),
        },
        "topic_predictions": [runner.versionable_topic_output(topic_output)],
        "topic_metrics": {
            "controlled_vocabulary": vocabulary,
            "by_split": topic_by_split,
            "test_bootstrap_95_ci": runner.bootstrap_metrics(
                [topic_output],
                lambda sampled: runner.topic_bootstrap_aggregate(sampled, vocabulary),
                cluster_key="cluster_id",
                unit="paper",
            ),
        },
    }
    restricted = {
        "qa_full_raw": [
            {
                "case_id": "qa-unit",
                "split": "test",
                "case": runner.redact_json_strings(qa_cases[0]),
                "response": runner.redact_json_strings(qa_response),
                "restriction": "operator-local",
            }
        ],
        "finder_full_raw": [
            {
                "profile_id": "finder-unit",
                "split": "test",
                "case": runner.redact_json_strings(finder_cases[0]),
                "retrieval": runner.redact_json_strings(retrieval),
                "evidence_only": runner.redact_json_strings(baseline),
                "full_finder": runner.redact_json_strings(full),
                "restriction": "operator-local",
            }
        ],
        "topic_full_raw": [{**topic_output, "restriction": "operator-local"}],
    }
    return decoded, restricted, qa_cases, finder_cases, topic_cases


def test_v2_strict_validator_recomputes_reviews_disagreements_and_bootstraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = load_module(
        "validate_peer_review_remediation_v2.py",
        "peer_review_strict_recomputation_v2",
    )
    decoded, restricted, qa_cases, finder_cases, topic_cases = (
        _strict_recomputation_fixture(validator)
    )
    frozen_hashes = {
        "chunk-1": {
            "chunk_text_sha256": "a" * 64,
            "effective_source_sha256": "b" * 64,
        }
    }
    monkeypatch.setattr(
        validator,
        "_source_hashes_from_frozen_database",
        lambda chunk_ids, _location: {
            chunk_id: frozen_hashes[chunk_id] for chunk_id in chunk_ids
        },
    )
    arguments = {
        "qa_cases": qa_cases,
        "finder_cases": finder_cases,
        "topic_cases": topic_cases,
    }

    report = validator.validate_strict_recomputation(
        decoded, restricted, **arguments
    )

    assert report["restricted_versionable_projections_exact"] is True
    assert "not independent or human review" in report["reviewer_boundary"]

    mutations = [
        ("QA pass 2", lambda value: value["qa_pass2"][0].update(actual_answered=False)),
        ("QA disagreements", lambda value: value["qa_disagreements"].update(disagreement_count=1)),
        (
            "QA seeded bootstrap",
            lambda value: value["qa_metrics"]["test_bootstrap_95_ci"].update(seed=-1),
        ),
        (
            "Finder pass 1",
            lambda value: value["finder_pass1"][0].update(full_finder_gold_rank=None),
        ),
        (
            "topic seeded bootstrap",
            lambda value: value["topic_metrics"]["test_bootstrap_95_ci"].update(seed=-1),
        ),
    ]
    for expected_error, mutate in mutations:
        tampered = json.loads(json.dumps(decoded))
        mutate(tampered)
        with pytest.raises(AssertionError, match=expected_error):
            validator.validate_strict_recomputation(
                tampered, restricted, **arguments
            )

    tampered_restricted = json.loads(json.dumps(restricted))
    tampered_restricted["qa_full_raw"][0]["response"]["answer"] = "different answer"
    with pytest.raises(AssertionError, match="qa versionable projection"):
        validator.validate_strict_recomputation(
            decoded, tampered_restricted, **arguments
        )

    tampered_source_identity = json.loads(json.dumps(decoded))

    def replace_effective_hash(value):
        if isinstance(value, dict):
            if value.get("chunk_id") == "chunk-1" and "effective_source_sha256" in value:
                value["effective_source_sha256"] = "c" * 64
            for child in value.values():
                replace_effective_hash(child)
        elif isinstance(value, list):
            for child in value:
                replace_effective_hash(child)

    replace_effective_hash(tampered_source_identity["qa_raw"])
    with pytest.raises(AssertionError, match="QA frozen source identities"):
        validator.validate_strict_recomputation(
            tampered_source_identity, restricted, **arguments
        )


def test_v2_normalized_hash_excludes_only_runtime_timestamps(tmp_path: Path) -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_normalized_hash_v2")
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    third = tmp_path / "third.jsonl"
    first.write_text(json.dumps({"case_id": "a", "generated_at": "first", "score": 1}) + "\n")
    second.write_text(json.dumps({"case_id": "a", "generated_at": "second", "score": 1}) + "\n")
    third.write_text(json.dumps({"case_id": "a", "generated_at": "second", "score": 2}) + "\n")

    assert runner.normalized_artifact_sha256(first) == runner.normalized_artifact_sha256(second)
    assert runner.normalized_artifact_sha256(first) != runner.normalized_artifact_sha256(third)


def test_v2_ocr_fixture_records_logical_font_identity_only() -> None:
    runner = load_module("run_peer_review_remediation_v2.py", "peer_review_ocr_font_v2")
    gold = json.loads(runner.OCR_GOLD_PATH.read_text(encoding="utf-8"))
    generation = gold["generation"]

    assert generation["font_id"] == runner.OCR_FIXTURE_FONT_ID
    assert generation["font_sha256"] == runner.sha256_file(runner.OCR_FIXTURE_FONT_PATH)
    assert "font_path" not in generation


def test_v2_ocr_fixture_is_raster_only_when_prepared() -> None:
    fixture = EVALUATION_DIR / "ocr_scanned_fixture_v2.pdf"
    if not fixture.exists():
        pytest.skip("OCR fixture is created by remediation-v2 prepare")
    document = fitz.open(fixture)
    try:
        assert document.page_count == 1
        assert document[0].get_text("text").strip() == ""
        assert document[0].get_images(full=True)
    finally:
        document.close()


def test_completed_v2_bundle_has_shuffled_passes_and_no_overclaim() -> None:
    manifest = ROOT / "artifacts" / "peer_review_remediation" / "v2" / "manifest_v2.json"
    if not manifest.exists():
        pytest.skip("completed remediation-v2 bundle is not present yet")
    validator = load_module("validate_peer_review_remediation_v2.py", "peer_review_validator_completed_v2")
    report = validator.validate_completed(require_restricted=False)

    assert report["status"] == "pass"
    assert report["qa_passes"]["orders_differ"] is True
    assert report["finder_passes"]["orders_differ"] is True
