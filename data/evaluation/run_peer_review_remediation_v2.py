#!/usr/bin/env python3
"""Prepare and execute the preregistered peer-review remediation v2 suite.

The prepare and evaluate commands are intentionally separate. ``prepare``
freezes dataset, corpus, historical-artifact, and implementation hashes before
any retrieval or generation call. ``evaluate`` refuses to run if a frozen input
has changed and never opens the tracked SQLite database for writing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import random
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "evaluation"
CANONICAL_OUT_RELATIVE = Path("artifacts/peer_review_remediation/v2")
CANONICAL_OUT_DIR = ROOT / CANONICAL_OUT_RELATIVE
OUT_DIR = Path(
    os.environ.get(
        "TTLAB_V2_ARTIFACT_DIR",
        str(CANONICAL_OUT_DIR),
    )
).resolve()
RESTRICTED_OUT_DIR = Path(
    os.environ.get(
        "TTLAB_V2_RESTRICTED_DIR",
        str(ROOT / "tmp" / "restricted" / "peer_review_remediation" / "v2"),
    )
).resolve()
PROTOCOL_PATH = DATA_DIR / "peer_review_remediation_v2_protocol.json"
QA_PATH = DATA_DIR / "qa_selective_response_v2.jsonl"
FINDER_PATH = DATA_DIR / "finder_proxy_profiles_v2.jsonl"
TOPIC_PATH = DATA_DIR / "topic_source_labels_v2.jsonl"
OCR_PDF_PATH = DATA_DIR / "ocr_scanned_fixture_v2.pdf"
OCR_GOLD_PATH = DATA_DIR / "ocr_scanned_fixture_v2.json"
RECEIPT_PATH = OUT_DIR / "freeze_receipt_v2.json"
VALIDATION_ATTESTATION_PATH = OUT_DIR / "validation_attestation_v2.json"
DB_PATH = ROOT / "data" / "papers.db"
LOCK_PATH = ROOT / "backend" / "requirements-lock.txt"
GENERATION_ARTIFACT_DIRS = (
    ROOT / "data" / "pdfs",
    ROOT / "data" / "extracted_text",
    ROOT / "data" / "chunks",
)

CODE_PATHS = sorted({
    Path(__file__).resolve(),
    DATA_DIR / "validate_peer_review_remediation_v2.py",
    ROOT / "backend" / "requirements-lock.txt",
    ROOT / "scripts" / "reproduce_all.sh",
    *(ROOT / "backend" / "app").rglob("*.py"),
}, key=lambda path: path.as_posix())

EVALUATION_ENVIRONMENT = {
    "TTLAB_ALLOWED_LLM_PROVIDERS": '["offline_extractive"]',
    "TTLAB_DEFAULT_LLM_PROVIDER": "offline_extractive",
}
TECHNICAL_SELECTION_PREDICATE = (
    "Paper.corpus_eligibility_status == eligible AND "
    "Paper.extraction_generation_id IS NOT NULL AND "
    "Paper.chunk_generation_id IS NOT NULL AND "
    "Paper.chunk_extraction_generation_id == Paper.extraction_generation_id AND "
    "Chunk.extraction_generation_id == Paper.extraction_generation_id"
)
PUBLIC_SELECTION_PREDICATE = (
    "review_status approved AND publication_status published AND rights_status cleared AND "
    "public_access_level searchable AND corpus_eligibility_status eligible AND "
    "extraction_review_status approved AND extraction_generation_id IS NOT NULL AND "
    "chunk_generation_id IS NOT NULL AND chunk_extraction_generation_id == extraction_generation_id AND "
    "public_index_generation_id == chunk_generation_id AND chunk_count > 0 AND "
    "Chunk.extraction_generation_id == Paper.extraction_generation_id"
)

HISTORICAL_PATHS = [
    ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    ROOT / "artifacts" / "phase4" / "topic_author" / "topic_metrics.json",
]

OUTPUT_PATHS = {
    "qa_raw": OUT_DIR / "qa_raw_outputs_v2.jsonl",
    "qa_pass1": OUT_DIR / "qa_review_pass1_v2.jsonl",
    "qa_pass2": OUT_DIR / "qa_review_pass2_v2.jsonl",
    "qa_disagreements": OUT_DIR / "qa_disagreements_v2.json",
    "qa_metrics": OUT_DIR / "qa_metrics_v2.json",
    "finder_raw": OUT_DIR / "finder_raw_outputs_v2.jsonl",
    "finder_pass1": OUT_DIR / "finder_review_pass1_v2.jsonl",
    "finder_pass2": OUT_DIR / "finder_review_pass2_v2.jsonl",
    "finder_disagreements": OUT_DIR / "finder_disagreements_v2.json",
    "finder_metrics": OUT_DIR / "finder_metrics_v2.json",
    "topic_predictions": OUT_DIR / "topic_predictions_v2.jsonl",
    "topic_metrics": OUT_DIR / "topic_metrics_v2.json",
    "ocr_results": OUT_DIR / "ocr_fixture_results_v2.json",
    "manuscript_macros": OUT_DIR / "manuscript_macros_v2.tex",
    "manifest": OUT_DIR / "manifest_v2.json",
}
RESTRICTED_OUTPUT_PATHS = {
    "qa_full_raw": RESTRICTED_OUT_DIR / "qa_full_raw_v2.jsonl",
    "finder_full_raw": RESTRICTED_OUT_DIR / "finder_full_raw_v2.jsonl",
    "topic_full_raw": RESTRICTED_OUT_DIR / "topic_full_raw_v2.jsonl",
}

DETERMINISTIC_COMPARISON_FILENAMES = (
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
)

OCR_FIXTURE_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
OCR_FIXTURE_FONT_ID = "dejavu-sans-system-v1"

REVIEWER = {
    "reviewer_id": "codex-ai-review",
    "reviewer_type": "ai",
    "label_tier": "ai_silver",
    "human_review": False,
    "independent_human_raters": 0,
    "entailment_verified": False,
    "pass_interpretation": "same_ai_procedure_repeatability_not_inter_rater_reliability",
}

REVIEW_SEEDS = {"pass_1": 1429, "pass_2": 2718}
BOOTSTRAP_SEED = 20260720
BOOTSTRAP_REPLICATES = 5000
FINDER_SCORE_WEIGHTS = {
    "retrieval_relevance": 0.30,
    "interest_topic_match": 0.20,
    "skill_match": 0.15,
    "data_feasibility": 0.10,
    "timeline_feasibility": 0.10,
    "difficulty_match": 0.10,
    "evidence_strength": 0.05,
}
GENERATION_RECONCILIATION_FIELDS = {
    "attempted",
    "reconciled",
    "already_current",
    "quarantined",
    "reasons",
    "dry_run",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        for row in rows:
            stream.write(canonical_json(row) + "\n")
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    """Atomically write a UTF-8 text artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value)
    temporary.replace(path)


def text_attestation(value: Any) -> dict[str, Any]:
    """Return content-free evidence that a text value existed in the local run."""

    normalized = redact_text(value)
    encoded = normalized.encode("utf-8")
    return {
        "sha256": sha256_bytes(encoded),
        "utf8_bytes": len(encoded),
        "word_count": len(normalized.split()),
    }


def structural_citation(citation: dict[str, Any]) -> dict[str, Any]:
    """Project a citation to versionable identifiers, hashes, and locators only."""

    return {
        key: citation.get(key)
        for key in (
            "paper_id",
            "chunk_id",
            "chunk_text_sha256",
            "effective_source_sha256",
            "section",
            "page_start",
            "page_end",
            "score",
            "scores",
        )
        if key in citation
    }


def validate_output_separation() -> None:
    """Ensure rights-sensitive raw outputs cannot enter canonical artifacts."""

    if (
        RESTRICTED_OUT_DIR == OUT_DIR
        or RESTRICTED_OUT_DIR.is_relative_to(OUT_DIR)
        or OUT_DIR.is_relative_to(RESTRICTED_OUT_DIR)
    ):
        raise ValueError("restricted v2 raw outputs must be outside the canonical output tree")
    if RESTRICTED_OUT_DIR.is_relative_to(ROOT):
        ignored = subprocess.run(
            [
                "git",
                "check-ignore",
                "--quiet",
                "--",
                relative(RESTRICTED_OUT_DIR / "rights-sensitive-probe.jsonl"),
            ],
            cwd=ROOT,
            check=False,
            timeout=15,
        )
        if ignored.returncode != 0:
            raise ValueError("repository-local restricted v2 output directory is not git-ignored")


def restricted_output_inventory() -> dict[str, Any]:
    """Create a content-free inventory without disclosing operator-local paths."""

    missing = [name for name, path in RESTRICTED_OUTPUT_PATHS.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required restricted raw outputs: {missing}")
    return {
        "required": True,
        "retained_locally": True,
        "committed": False,
        "release_included": False,
        "lawful_local_corpus_access_required_for_exact_reproduction": True,
        "files": {
            name: {
                "filename": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for name, path in sorted(RESTRICTED_OUTPUT_PATHS.items())
        },
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{relative(path)}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{relative(path)}:{line_number}: expected a JSON object")
        rows.append(value)
    return rows


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("–", "-").replace("—", "-").replace("−", "-")
    normalized = re.sub(r"(?<=\w)-\s+(?=\w)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized.lower()).strip()
    return normalized


def package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def command_output(args: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(
            list(args),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def locked_validator_identity() -> dict[str, Any]:
    """Identify and validate the exact Python environment used by the validator.

    The identity is deliberately repository-logical: it records hashes and
    versions, never an operator-specific interpreter or filesystem path.
    """

    backend_path = str(ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from app.reproducibility.environment import validate_environment

    environment = validate_environment(LOCK_PATH)
    validator_path = DATA_DIR / "validate_peer_review_remediation_v2.py"
    return {
        "status": "locked_environment_valid",
        "python_version": sys.version.split()[0],
        "lock_path": relative(LOCK_PATH),
        "lock_sha256": sha256_file(LOCK_PATH),
        "locked_package_count": environment["locked_package_count"],
        "validator_path": relative(validator_path),
        "validator_sha256": sha256_file(validator_path),
        "runner_path": relative(Path(__file__).resolve()),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }


def invoke_locked_validator(*arguments: str) -> dict[str, Any]:
    """Run the validator with this process's lock-validated interpreter."""

    identity = locked_validator_identity()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "backend")
    completed = subprocess.run(
        [
            sys.executable,
            str(DATA_DIR / "validate_peer_review_remediation_v2.py"),
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no validator output"
        raise RuntimeError(f"locked-environment v2 validator failed: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("locked-environment v2 validator returned invalid JSON") from exc
    if report.get("status") != "pass":
        raise RuntimeError("locked-environment v2 validator did not attest a pass")
    return {"identity": identity, "report": report}


def _normalized_comparison_value(value: Any) -> Any:
    """Remove run-time clocks while retaining every structural decision."""

    if isinstance(value, dict):
        return {
            key: _normalized_comparison_value(child)
            for key, child in sorted(value.items())
            if key != "timestamp" and not key.endswith("_at")
        }
    if isinstance(value, list):
        return [_normalized_comparison_value(child) for child in value]
    return value


def normalized_artifact_sha256(path: Path) -> str:
    """Hash JSON/JSONL structurally, excluding only timestamp fields."""

    if path.suffix == ".jsonl":
        value: Any = read_jsonl(path)
        payload = canonical_json(_normalized_comparison_value(value)).encode("utf-8")
    elif path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        payload = canonical_json(_normalized_comparison_value(value)).encode("utf-8")
    else:
        payload = path.read_bytes()
    return sha256_bytes(payload)


def versionable_ocr_configuration(configuration: dict[str, Any] | None) -> dict[str, Any]:
    """Retain OCR identity hashes/configuration without host filesystem paths."""

    clean = json.loads(json.dumps(configuration or {}))
    language_data = clean.get("language_data")
    if isinstance(language_data, dict):
        language_data.pop("resolved_path", None)
        language_data["resolved_path_recorded"] = False
    return clean


def evaluation_source_paths() -> list[Path]:
    """Return every committed source whose exact state defines the v2 run."""

    return sorted(
        {
            PROTOCOL_PATH,
            QA_PATH,
            FINDER_PATH,
            TOPIC_PATH,
            OCR_PDF_PATH,
            OCR_GOLD_PATH,
            ROOT / "backend" / "tests" / "test_peer_review_remediation_v2.py",
            *CODE_PATHS,
        },
        key=lambda path: path.as_posix(),
    )


def evaluation_source_status() -> str:
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *[relative(path) for path in evaluation_source_paths()],
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def require_clean_committed_evaluation_sources() -> str:
    """Fail unless executable/backend/protocol inputs are committed and clean.

    Run-generated databases, historical artifacts, manuscripts, and output
    directories are intentionally outside this check. They are frozen by hash
    where used, but do not make the executable evaluation source ambiguous.
    """

    status = evaluation_source_status()
    if status:
        raise RuntimeError(
            "v2 evaluation sources must be clean and committed before prepare/evaluate: "
            + status.replace("\n", "; ")
        )
    commit = command_output(["git", "rev-parse", "HEAD"])
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("v2 evaluation source commit is unresolved")
    return commit


def ocr_runtime_identity() -> dict[str, Any]:
    """Capture the exact system/Python OCR identity frozen between commands."""

    backend_path = str(ROOT / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from app.ingestion.ocr import deterministic_ocr_configuration

    return {
        "tesseract": command_output(["tesseract", "--version"]),
        "configuration": versionable_ocr_configuration(deterministic_ocr_configuration()),
        "packages": {
            "pymupdf": package_version("PyMuPDF"),
            "pillow": package_version("Pillow"),
            "pytesseract": package_version("pytesseract"),
        },
    }


def git_state() -> dict[str, Any]:
    commit = command_output(["git", "rev-parse", "HEAD"])
    status = command_output(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    diff = command_output(["git", "diff", "--binary", "--", *[relative(path) for path in CODE_PATHS]])
    return {
        "head": commit,
        "dirty": bool(status),
        "status_sha256": sha256_bytes((status or "").encode("utf-8")),
        "evaluation_code_diff_sha256": sha256_bytes((diff or "").encode("utf-8")),
        "evaluation_sources_clean_and_committed": evaluation_source_status() == "",
        "note": "Executable/backend/protocol inputs are clean and committed. Run-generated data and manuscript outputs may be dirty and are governed by their own hashes.",
    }


def validate_static_protocol() -> dict[str, list[str]]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    datasets = {
        "ask": read_jsonl(QA_PATH),
        "finder": read_jsonl(FINDER_PATH),
        "topics": read_jsonl(TOPIC_PATH),
    }
    id_fields = {"ask": "case_id", "finder": "profile_id", "topics": "case_id"}
    frozen: dict[str, list[str]] = {}
    for section, rows in datasets.items():
        id_field = id_fields[section]
        actual_ids = [str(row[id_field]) for row in rows]
        if len(actual_ids) != len(set(actual_ids)):
            raise ValueError(f"duplicate {section} IDs")
        expected_dev = list(protocol[section]["frozen_dev_ids"])
        expected_test = list(protocol[section]["frozen_test_ids"])
        expected_sensitivity = list(protocol[section].get("frozen_sensitivity_ids", []))
        observed_dev = [str(row[id_field]) for row in rows if row.get("split") == "dev"]
        observed_test = [str(row[id_field]) for row in rows if row.get("split") == "test"]
        observed_sensitivity = [str(row[id_field]) for row in rows if row.get("split") == "sensitivity"]
        if (
            observed_dev != expected_dev
            or observed_test != expected_test
            or observed_sensitivity != expected_sensitivity
        ):
            raise ValueError(f"{section} frozen split IDs do not match the protocol")
        if set(actual_ids) != set(expected_dev + expected_test + expected_sensitivity):
            raise ValueError(f"{section} protocol and dataset ID sets differ")
        for row in rows:
            construction = row.get("construction") or {}
            if construction.get("rankings_consulted") is not False:
                raise ValueError(f"{section}:{row[id_field]} is not source-first")
            if section == "finder" and construction.get("method") != (
                "source_derived_need_profile_without_title_copy"
            ):
                raise ValueError(f"{section}:{row[id_field]} does not preserve the no-title-copy rule")
            if section == "ask":
                if bool(row.get("expected_answerable")):
                    if not row.get("gold_locator") or not row.get("answer_points") or row.get("negative_evidence"):
                        raise ValueError(f"ask:{row[id_field]} has an invalid answerable-case contract")
                else:
                    negative = row.get("negative_evidence") or {}
                    if (
                        construction.get("method") != "source_derived_in_domain_absence_probe"
                        or row.get("gold_locator") is not None
                        or row.get("answer_points") != []
                        or not negative.get("context_locator")
                        or not negative.get("absent_phrases")
                    ):
                        raise ValueError(f"ask:{row[id_field]} has an invalid in-domain near-miss contract")
        frozen[section] = actual_ids
    finder_pairs: dict[str, list[dict[str, Any]]] = {}
    for row in datasets["finder"]:
        if row.get("split") == "sensitivity" and not row.get("constraint_pair"):
            raise ValueError("every Finder sensitivity row must name its test-pair family")
        if row.get("constraint_pair"):
            finder_pairs.setdefault(str(row["constraint_pair"]), []).append(row)
    pair_invariants = (
        "interests",
        "skills",
        "project_type",
        "data_constraints",
        "preferred_topics",
        "gold_paper_id",
        "source_locator",
    )
    for pair_name, rows in finder_pairs.items():
        if len(rows) != 2 or {row.get("split") for row in rows} != {"test", "sensitivity"}:
            raise ValueError(f"Finder sensitivity pair {pair_name} must contain one test and one sensitivity row")
        if any(rows[0].get(key) != rows[1].get(key) for key in pair_invariants):
            raise ValueError(f"Finder sensitivity pair {pair_name} changes more than constraints")
        if (
            rows[0].get("available_time") == rows[1].get("available_time")
            or rows[0].get("preferred_difficulty") == rows[1].get("preferred_difficulty")
        ):
            raise ValueError(f"Finder sensitivity pair {pair_name} does not vary time and difficulty")
    if protocol["reviewer"]["reviewer_type"] != "ai" or protocol["reviewer"]["human_review"] is not False:
        raise ValueError("protocol must retain the AI-silver, non-human boundary")
    if protocol["ask"]["fixed_answerability_rule"]["tuning_on_v2"] is not False:
        raise ValueError("v2 threshold tuning is prohibited")
    if protocol["ask"].get("retrieval_mode") != "keyword" or protocol["ask"].get("retrieval_scope") != "technical":
        raise ValueError("Ask retrieval contract drift")
    if protocol["ask"].get("provider") != "offline_extractive":
        raise ValueError("Ask provider contract drift")
    if protocol["ask"].get("model_when_invoked") != "sentence-overlap-v1":
        raise ValueError("Ask model contract drift")
    if protocol["ask"].get("top_k") != 5 or protocol["ask"].get("max_words") != 180:
        raise ValueError("Ask generation/retrieval parameter drift")
    boundary = protocol.get("corpus_and_projection_boundary") or {}
    if boundary.get("technical_selection_predicate") != TECHNICAL_SELECTION_PREDICATE:
        raise ValueError("technical corpus predicate drift")
    if boundary.get("public_projection_evaluated") is not False:
        raise ValueError("v2 must not imply public-projection evaluation")
    if boundary.get("public_projection_predicate_recorded_not_tested") != PUBLIC_SELECTION_PREDICATE:
        raise ValueError("recorded public projection predicate drift")
    generation_link = boundary.get("generation_link_reconciliation") or {}
    if (
        generation_link.get("required_before_index_rebuild") is not True
        or generation_link.get("legacy_or_mismatched_artifacts") != "quarantine_fail_closed"
        or generation_link.get("zero_generation_linked_corpus_permitted") is not False
        or set(generation_link.get("receipt_fields") or []) != GENERATION_RECONCILIATION_FIELDS
    ):
        raise ValueError("generation-link reconciliation contract drift")
    provider_environment = protocol["ask"].get("provider_environment") or {}
    if provider_environment.get("allowed_llm_providers") != ["offline_extractive"]:
        raise ValueError("Ask provider allowlist must be frozen to offline_extractive")
    if provider_environment.get("default_llm_provider") != "offline_extractive":
        raise ValueError("Ask default provider must be frozen to offline_extractive")
    if provider_environment.get("external_provider_invoked") is not False:
        raise ValueError("v2 must not invoke an external generation provider")
    index_preparation = protocol["ask"].get("temporary_index_preparation") or {}
    if index_preparation.get("rebuild_keyword_index") is not True:
        raise ValueError("v2 must rebuild the keyword index on the temporary database")
    if index_preparation.get("live_database_mutated") is not False:
        raise ValueError("v2 must not rebuild the tracked database index")
    if protocol["finder"].get("score_weights") != FINDER_SCORE_WEIGHTS:
        raise ValueError("Finder score weights drift from the preregistration")
    if protocol["finder"].get("retrieval_mode") != "keyword" or protocol["finder"].get("top_k") != 3:
        raise ValueError("Finder retrieval contract drift")
    if (
        protocol["finder"].get("provider") != "offline_deterministic"
        or protocol["finder"].get("model") != "template-recommender-v1"
    ):
        raise ValueError("Finder provider/model contract drift")
    if protocol["ocr"].get("execution_path") != (
        "backend.app.ingestion.pdf_parser.extract_pdf_text with run_ocr=true and a TesseractOCRProvider"
    ):
        raise ValueError("OCR must exercise the full approved PDF extraction pipeline")
    ocr_protocol = protocol["ocr"]
    ocr_configuration = ocr_runtime_identity()["configuration"]
    expected_ocr = {
        "provider": "tesseract",
        "language": ocr_configuration.get("language"),
        "locale": (ocr_configuration.get("environment") or {}).get("LC_ALL"),
        "omp_thread_limit": int((ocr_configuration.get("environment") or {}).get("OMP_THREAD_LIMIT", "0")),
        "config": ocr_configuration.get("config"),
        "render_dpi": ocr_configuration.get("render_dpi"),
        "render_scale": ocr_configuration.get("render_scale"),
    }
    if any(ocr_protocol.get(key) != value for key, value in expected_ocr.items()):
        raise ValueError("OCR protocol/configuration drift")
    if ocr_protocol.get("parser_limits") != {"max_pdf_bytes": 5_242_880, "max_pdf_pages": 1}:
        raise ValueError("OCR parser-limit contract drift")
    bootstrap = protocol.get("bootstrap") or {}
    if (
        bootstrap.get("method") != "cluster_level_percentile_bootstrap"
        or bootstrap.get("replicates") != BOOTSTRAP_REPLICATES
        or bootstrap.get("seed") != BOOTSTRAP_SEED
        or bootstrap.get("confidence_level") != 0.95
    ):
        raise ValueError("bootstrap preregistration drift")
    provenance_contract = protocol.get("runtime_provenance_requirement") or {}
    if provenance_contract.get("technical_corpus_identity_contract") != "retrieval_source_identity_v2":
        raise ValueError("technical corpus identity contract drift")
    if provenance_contract.get("declared_source_ids_must_equal_serialized_retrieval_source_ids") is not True:
        raise ValueError("runtime source identity must be exhaustive")
    if provenance_contract.get("canonical_evaluation_sources_must_be_clean_and_committed") is not True:
        raise ValueError("clean committed evaluation sources are not required")
    if provenance_contract.get("pdf_extraction_and_chunk_artifact_inventory_frozen_before_execution") is not True:
        raise ValueError("generation-affecting local artifact inventory is not frozen")
    if protocol["historical_v1"]["classification"] != "historical_post_selection_descriptive":
        raise ValueError("v1 ablations must remain historical post-selection evidence")
    if protocol["topics"].get("label_scope") != "positive_only_not_exhaustive_closed_world":
        raise ValueError("topic labels must remain positive-only rather than invented closed-world gold")
    prohibited_topic_metrics = {"micro_precision", "micro_f1", "exact_match_rate"}
    if prohibited_topic_metrics.intersection(protocol["topics"].get("primary_metrics") or []):
        raise ValueError("positive-only topic labels cannot support precision, F1, or exact match")
    output_contract = protocol.get("output_contract") or {}
    if output_contract.get("canonical_directory") != relative(CANONICAL_OUT_DIR):
        raise ValueError("v2 canonical output directory drift")
    if output_contract.get("manuscript_macros") != OUTPUT_PATHS["manuscript_macros"].name:
        raise ValueError("v2 manuscript macro output contract drift")
    if output_contract.get("validation_attestation") != VALIDATION_ATTESTATION_PATH.name:
        raise ValueError("v2 completed-package attestation contract drift")
    if output_contract.get("validation_execution") != (
        "locked_python_environment_before_freeze_and_after_completed_package"
    ):
        raise ValueError("v2 locked-validator execution contract drift")
    if output_contract.get("release_filename_policy") != "exact_allowlist_only":
        raise ValueError("v2 release filename policy drift")
    if output_contract.get("structural_reproduction_comparison") != (
        "all case-level outputs normalized by excluding timestamp fields only"
    ):
        raise ValueError("v2 structural reproduction comparison contract drift")
    if output_contract.get("hand_entered_manuscript_metrics_permitted") is not False:
        raise ValueError("v2 must not permit hand-entered manuscript metrics")
    restricted = output_contract.get("restricted_raw_output_policy") or {}
    if (
        restricted.get("required") is not True
        or restricted.get("commit_or_release_permitted") is not False
        or restricted.get("manifest_records_sha256_and_size") is not True
        or restricted.get("lawful_local_corpus_access_required_for_reproduction") is not True
    ):
        raise ValueError("restricted raw output boundary drift")
    return frozen


def frozen_dataset_identity() -> dict[str, Any]:
    """Return the exact ordered IDs and split assignments frozen by protocol."""

    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    definitions = {
        "ask": (QA_PATH, "case_id"),
        "finder": (FINDER_PATH, "profile_id"),
        "topics": (TOPIC_PATH, "case_id"),
    }
    identity: dict[str, Any] = {}
    for section, (path, id_field) in definitions.items():
        rows = read_jsonl(path)
        splits = {
            split: [str(row[id_field]) for row in rows if row.get("split") == split]
            for split in ("dev", "test", "sensitivity")
        }
        if not splits["sensitivity"]:
            splits.pop("sensitivity")
        expected = {
            "dev": list(protocol[section]["frozen_dev_ids"]),
            "test": list(protocol[section]["frozen_test_ids"]),
        }
        sensitivity = list(protocol[section].get("frozen_sensitivity_ids", []))
        if sensitivity:
            expected["sensitivity"] = sensitivity
        if splits != expected:
            raise RuntimeError(f"{section} ordered frozen split identity drift")
        identity[section] = {
            "id_field": id_field,
            "dataset_path": relative(path),
            "dataset_sha256": sha256_file(path),
            "case_count": len(rows),
            "splits": splits,
        }
    return identity


def validate_sqlite_source_locators() -> None:
    """Validate every prospective locator without running retrieval or generation."""

    locators: list[tuple[str, dict[str, Any], str]] = []
    qa_cases = read_jsonl(QA_PATH)
    for case in qa_cases:
        if case.get("gold_locator"):
            locators.append((str(case["case_id"]), case["gold_locator"], str(case["gold_locator"]["paper_id"])))
        negative = case.get("negative_evidence") or {}
        if negative:
            locators.append(
                (str(case["case_id"]), negative["context_locator"], str(negative["paper_id"]))
            )
    for case in read_jsonl(FINDER_PATH):
        locators.append((str(case["profile_id"]), case["source_locator"], str(case["gold_paper_id"])))
    for case in read_jsonl(TOPIC_PATH):
        locators.append((str(case["case_id"]), case["source_locator"], str(case["paper_id"])))
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        for item_id, locator, expected_paper_id in locators:
            row = connection.execute(
                "SELECT c.source_hash, c.text, c.paper_id, p.corpus_eligibility_status, "
                "c.page_start, c.page_end, c.section "
                "FROM chunk c JOIN paper p ON p.paper_id = c.paper_id WHERE c.chunk_id = ?",
                (str(locator["chunk_id"]),),
            ).fetchone()
            if row is None:
                raise ValueError(f"{item_id}: source chunk does not exist: {locator['chunk_id']}")
            source_hash, text, paper_id, eligibility, page_start, page_end, section = row
            if paper_id != expected_paper_id:
                raise ValueError(f"{item_id}: source locator belongs to unexpected paper {paper_id}")
            if locator.get("paper_id") not in {None, expected_paper_id}:
                raise ValueError(f"{item_id}: locator paper_id drift")
            if eligibility != "eligible":
                raise ValueError(f"{item_id}: source paper is not in the technical eligible corpus")
            if source_hash != locator["source_hash"]:
                raise ValueError(f"{item_id}: source hash mismatch")
            computed_hash = sha256_bytes(str(text or "").encode("utf-8"))
            if computed_hash != source_hash:
                raise ValueError(f"{item_id}: persisted source hash does not match exact chunk text")
            if normalize_text(locator["anchor"]) not in normalize_text(str(text or "")):
                raise ValueError(f"{item_id}: source anchor not present: {locator['anchor']}")
            for key, observed in (("page_start", page_start), ("page_end", page_end), ("section", section)):
                if key in locator and locator.get(key) != observed:
                    raise ValueError(
                        f"{item_id}: source locator {key} drift: expected={locator.get(key)!r}, observed={observed!r}"
                    )
        for case in qa_cases:
            if case.get("gold_locator"):
                text_row = connection.execute(
                    "SELECT text FROM chunk WHERE chunk_id = ?",
                    (str(case["gold_locator"]["chunk_id"]),),
                ).fetchone()
                source_text = normalize_text(str(text_row[0] if text_row else ""))
                source_tokens = set(re.findall(r"[a-z0-9]+", source_text))
                for point in case.get("answer_points", []):
                    for alternatives in point.get("groups", []):
                        if not any(
                            set(re.findall(r"[a-z0-9]+", normalize_text(term))).issubset(source_tokens)
                            for term in alternatives
                        ):
                            raise ValueError(
                                f"{case['case_id']}:{point.get('point_id')}: answer-point group lacks lexical support in the gold chunk"
                            )
                continue
            negative = case.get("negative_evidence") or {}
            paper_id = str(negative.get("paper_id") or "")
            full_text = " ".join(
                str(row[0] or "")
                for row in connection.execute(
                    "SELECT text FROM chunk WHERE paper_id = ? ORDER BY chunk_index, chunk_id",
                    (paper_id,),
                ).fetchall()
            )
            normalized_full_text = normalize_text(full_text)
            if not normalized_full_text:
                raise ValueError(f"{case['case_id']}: near-miss paper has no frozen text")
            for phrase in negative.get("absent_phrases", []):
                if normalize_text(phrase) in normalized_full_text:
                    raise ValueError(
                        f"{case['case_id']}: declared absent phrase occurs in the named paper: {phrase!r}"
                    )
        for case in read_jsonl(FINDER_PATH):
            title_row = connection.execute(
                "SELECT title FROM paper WHERE paper_id = ?",
                (str(case["gold_paper_id"]),),
            ).fetchone()
            if title_row is None:
                raise ValueError(f"{case['profile_id']}: gold paper is missing")
            if normalize_text(str(title_row[0])) in normalize_text(str(case["interests"])):
                raise ValueError(f"{case['profile_id']}: interest statement copies the gold title")
    finally:
        connection.close()


def corpus_snapshot() -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        paper_count = int(connection.execute("SELECT COUNT(*) FROM paper").fetchone()[0])
        chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunk").fetchone()[0])
        eligible_papers = int(
            connection.execute(
                "SELECT COUNT(*) FROM paper WHERE corpus_eligibility_status = 'eligible'"
            ).fetchone()[0]
        )
        eligible_chunks = int(
            connection.execute(
                "SELECT COUNT(*) FROM chunk c JOIN paper p ON p.paper_id = c.paper_id "
                "WHERE p.corpus_eligibility_status = 'eligible'"
            ).fetchone()[0]
        )
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        logical_digest = hashlib.sha256()
        for table_name in ("paper", "chunk"):
            columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()]
            logical_digest.update(canonical_json({"table": table_name, "columns": columns}).encode("utf-8"))
            for row in connection.execute(f"SELECT * FROM {table_name} ORDER BY {columns[0]}"):
                encoded_row = [
                    {"blob_hex": bytes(value).hex()} if isinstance(value, (bytes, bytearray, memoryview)) else value
                    for value in row
                ]
                logical_digest.update(canonical_json(encoded_row).encode("utf-8"))
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    return {
        "paper_rows": paper_count,
        "chunk_rows": chunk_count,
        "technical_eligible_papers": eligible_papers,
        "technical_eligible_chunks": eligible_chunks,
        "sqlite_schema_sha256": sha256_bytes(canonical_json(schema_rows).encode("utf-8")),
        "paper_chunk_logical_sha256": logical_digest.hexdigest(),
        "sqlite_integrity_check": integrity,
    }


def generate_ocr_fixture() -> dict[str, Any]:
    import fitz
    from PIL import Image, ImageDraw, ImageFont

    font_path = OCR_FIXTURE_FONT_PATH
    if not font_path.is_file():
        raise FileNotFoundError(font_path)
    lines = [
        "TTLAB OCR PIPELINE FIXTURE V2",
        "Document ID: OCR-2026-0720",
        "Full-paper evidence must remain traceable.",
        "Page 1 records rainfall, crop price, and energy demand.",
        "Values: 23 manuals; 116 schools; alpha = 0.5.",
        "Symbols: ARIMA, SARIMAX, JSON, XML, and RAG.",
        "This raster-only page has no embedded text layer.",
    ]
    width, height = 1224, 1584
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font_path), 52)
    body_font = ImageFont.truetype(str(font_path), 38)
    y = 155
    draw.text((100, y), lines[0], fill="black", font=title_font)
    y += 130
    for line in lines[1:]:
        draw.text((100, y), line, fill="black", font=body_font)
        y += 105
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as stream:
        png_path = Path(stream.name)
    try:
        image.save(png_path, format="PNG", optimize=False, compress_level=9)
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=str(png_path), keep_proportion=False)
        document.set_metadata(
            {
                "title": "TTLAB OCR Pipeline Fixture V2",
                "author": "codex-ai-review",
                "subject": "Deterministic raster-only OCR pipeline fixture; not corpus accuracy evidence",
                "keywords": "OCR, raster-only, evaluation-v2",
                "creator": "Pillow and PyMuPDF",
                "producer": "PyMuPDF",
                "creationDate": "D:20260720000000+00'00'",
                "modDate": "D:20260720000000+00'00'",
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", dir=DATA_DIR, delete=False) as stream:
            temporary_pdf = Path(stream.name)
        document.save(temporary_pdf, garbage=4, deflate=True, clean=True, no_new_id=True)
        document.close()
        temporary_pdf.replace(OCR_PDF_PATH)
    finally:
        png_path.unlink(missing_ok=True)
    ground_truth = {
        "fixture_id": "ocr-scanned-fixture-v2",
        "schema_version": 2,
        "page_count": 1,
        "ground_truth_lines": lines,
        "ground_truth_text": " ".join(lines),
        "generation": {
            "page_points": [612, 792],
            "raster_pixels": [width, height],
            "raster_color_mode": "RGB",
            "alpha": False,
            "background": "white",
            "foreground": "black",
            "font_id": OCR_FIXTURE_FONT_ID,
            "font_sha256": sha256_file(font_path),
            "title_font_size": 52,
            "body_font_size": 38,
            "pillow_version": package_version("Pillow"),
            "pymupdf_version": package_version("PyMuPDF"),
        },
        "claim_boundary": "This raster-only synthetic fixture exercises the OCR pipeline; it is not TTLAB corpus OCR-accuracy evidence.",
    }
    write_json(OCR_GOLD_PATH, ground_truth)
    return ground_truth


def frozen_input_paths() -> list[Path]:
    return sorted({
        PROTOCOL_PATH,
        QA_PATH,
        FINDER_PATH,
        TOPIC_PATH,
        OCR_PDF_PATH,
        OCR_GOLD_PATH,
        DB_PATH,
        *CODE_PATHS,
        *HISTORICAL_PATHS,
        *generation_artifact_paths(),
    }, key=lambda path: path.as_posix())


def generation_artifact_paths() -> list[Path]:
    """Inventory every local file that can affect generation reconciliation."""

    paths: list[Path] = []
    for directory in GENERATION_ARTIFACT_DIRS:
        if not directory.is_dir():
            continue
        paths.extend(path for path in directory.rglob("*") if path.is_file() and path.name != ".gitkeep")
    return sorted(paths, key=lambda path: path.as_posix())


def generation_artifact_inventory() -> dict[str, Any]:
    files = generation_artifact_paths()
    descriptors = {
        relative(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in files
    }
    return {
        "directories": [relative(path) for path in GENERATION_ARTIFACT_DIRS],
        "file_count": len(files),
        "inventory_sha256": sha256_bytes(canonical_json(descriptors).encode("utf-8")),
    }


def freeze_inputs() -> None:
    validate_output_separation()
    evaluation_source_commit = require_clean_committed_evaluation_sources()
    validate_static_protocol()
    validate_sqlite_source_locators()
    if RECEIPT_PATH.exists():
        raise FileExistsError(f"freeze receipt already exists: {relative(RECEIPT_PATH)}")
    if any(path.exists() for path in OUTPUT_PATHS.values()):
        raise FileExistsError("evaluation outputs already exist; refusing to overwrite a prior run")
    if any(path.exists() for path in RESTRICTED_OUTPUT_PATHS.values()):
        raise FileExistsError("restricted evaluation outputs already exist; refusing to overwrite a prior run")
    if VALIDATION_ATTESTATION_PATH.exists():
        raise FileExistsError(
            f"validation attestation already exists: {relative(VALIDATION_ATTESTATION_PATH)}"
        )
    generate_ocr_fixture()
    if require_clean_committed_evaluation_sources() != evaluation_source_commit:
        raise RuntimeError("evaluation source commit changed while preparing the freeze")
    locked_validation = invoke_locked_validator("--static-only")
    if require_clean_committed_evaluation_sources() != evaluation_source_commit:
        raise RuntimeError("evaluation source commit changed during locked-environment validation")
    frozen_paths = frozen_input_paths()
    missing = [relative(path) for path in frozen_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing frozen inputs: {missing}")
    receipt = {
        "freeze_id": "peer-review-remediation-v2-freeze",
        "status": "frozen_before_execution",
        "frozen_at": utc_now(),
        "protocol_id": "peer-review-remediation-v2",
        "source_database_open_mode_for_execution": "read_source_via_sqlite_backup_then_mutate_temporary_copy_only",
        "corpus_snapshot": corpus_snapshot(),
        "retrieval_scope": "technical",
        "technical_selection_predicate": TECHNICAL_SELECTION_PREDICATE,
        "public_projection_evaluated": False,
        "public_selection_predicate_recorded_not_tested": PUBLIC_SELECTION_PREDICATE,
        "temporary_keyword_index_rebuild_required": True,
        "generation_artifact_inventory": generation_artifact_inventory(),
        "evaluation_source_commit": evaluation_source_commit,
        "frozen_dataset_identity": frozen_dataset_identity(),
        "locked_validator_identity": locked_validation["identity"],
        "static_validation_report_sha256": sha256_bytes(
            canonical_json(locked_validation["report"]).encode("utf-8")
        ),
        "provider_environment_overrides": EVALUATION_ENVIRONMENT,
        "threshold_tuning": False,
        "reviewer": REVIEWER,
        "files": {relative(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size} for path in frozen_paths},
        "git": git_state(),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "host_locale_before_ocr_override": command_output(["locale"]),
            "ocr_identity": ocr_runtime_identity(),
            "sqlmodel": package_version("sqlmodel"),
        },
        "historical_v1_interpretation": "immutable_historical_post_selection_descriptive",
        "bootstrap": {
            "method": "cluster_level_percentile_bootstrap",
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "cluster_units": json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))["bootstrap"][
                "cluster_units"
            ],
            "label_uncertainty_included": False,
            "corpus_selection_uncertainty_included": False,
        },
    }
    write_json(RECEIPT_PATH, receipt)
    print(f"Frozen {len(frozen_paths)} inputs in {relative(RECEIPT_PATH)}", flush=True)


def verify_frozen_inputs() -> dict[str, Any]:
    validate_output_separation()
    evaluation_source_commit = require_clean_committed_evaluation_sources()
    validate_static_protocol()
    if not RECEIPT_PATH.is_file():
        raise FileNotFoundError("run prepare before evaluate")
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    if receipt.get("evaluation_source_commit") != evaluation_source_commit:
        raise RuntimeError("evaluation source commit differs from the frozen commit")
    if receipt.get("locked_validator_identity") != locked_validator_identity():
        raise RuntimeError("locked validator/environment identity changed after prepare")
    if receipt.get("frozen_dataset_identity") != frozen_dataset_identity():
        raise RuntimeError("frozen dataset ID/split identity changed after prepare")
    if ((receipt.get("runtime") or {}).get("ocr_identity")) != ocr_runtime_identity():
        raise RuntimeError("OCR runtime, traineddata, or deterministic configuration changed after prepare")
    expected_inventory = {relative(path) for path in frozen_input_paths()}
    observed_inventory = set(receipt.get("files", {}))
    if observed_inventory != expected_inventory:
        added = sorted(observed_inventory - expected_inventory)
        missing = sorted(expected_inventory - observed_inventory)
        raise RuntimeError(f"frozen input inventory drift: added={added}, missing={missing}")
    mismatches: list[str] = []
    for raw_path, expected in receipt["files"].items():
        path = ROOT / raw_path
        if not path.is_file():
            mismatches.append(f"missing:{raw_path}")
            continue
        observed = sha256_file(path)
        if observed != expected["sha256"]:
            mismatches.append(f"sha256:{raw_path}")
    if mismatches:
        raise RuntimeError(f"frozen inputs changed after prepare: {mismatches}")
    if corpus_snapshot() != receipt["corpus_snapshot"]:
        raise RuntimeError("logical paper/chunk corpus changed after prepare")
    if generation_artifact_inventory() != receipt.get("generation_artifact_inventory"):
        raise RuntimeError("PDF/extraction/chunk generation artifact inventory changed after prepare")
    existing = [relative(path) for path in OUTPUT_PATHS.values() if path.exists()]
    existing.extend(path.name for path in RESTRICTED_OUTPUT_PATHS.values() if path.exists())
    if VALIDATION_ATTESTATION_PATH.exists():
        existing.append(relative(VALIDATION_ATTESTATION_PATH))
    if existing:
        raise FileExistsError(f"refusing to overwrite evaluation outputs: {existing}")
    return receipt


def initialize_temporary_database(temp_dir: Path) -> Path:
    temp_db = temp_dir / "papers_v2_eval.db"
    source = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    target = sqlite3.connect(temp_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    os.environ["TTLAB_DATABASE_URL"] = f"sqlite:///{temp_db.as_posix()}"
    for key, value in EVALUATION_ENVIRONMENT.items():
        os.environ[key] = value
    return temp_db


def validate_generation_reconciliation(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != GENERATION_RECONCILIATION_FIELDS:
        raise RuntimeError("generation reconciliation receipt is missing or has schema drift")
    if receipt.get("dry_run") is not False:
        raise RuntimeError("generation reconciliation must be applied to the temporary database")
    counts = {
        key: int(receipt.get(key, -1))
        for key in ("attempted", "reconciled", "already_current", "quarantined")
    }
    if any(value < 0 for value in counts.values()):
        raise RuntimeError("generation reconciliation receipt contains a negative count")
    if counts["attempted"] != (
        counts["reconciled"] + counts["already_current"] + counts["quarantined"]
    ):
        raise RuntimeError("generation reconciliation receipt counts do not balance")
    reasons = receipt.get("reasons")
    if not isinstance(reasons, dict) or sum(int(value) for value in reasons.values()) != counts["quarantined"]:
        raise RuntimeError("generation reconciliation quarantine reasons do not balance")
    return receipt


def prepare_temporary_keyword_index(
    session: Any,
    *,
    generation_reconciliation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and verify the technical keyword index on the disposable DB only."""

    from app.indexing.embedder import corpus_descriptor, eligible_chunks
    from app.indexing.keyword_search import (
        diagnostics,
        keyword_index_metadata,
        rebuild_keyword_index,
    )

    reconciliation = validate_generation_reconciliation(generation_reconciliation)
    chunks = eligible_chunks(session)
    corpus = corpus_descriptor(session, chunks)
    if int(corpus["eligible_chunk_count"]) <= 0 or int(corpus["eligible_paper_count"]) <= 0:
        raise RuntimeError(
            "temporary evaluation corpus has no generation-linked eligible papers/chunks; "
            "run deterministic extraction and chunking, then reconcile generation links"
        )
    if int(reconciliation["reconciled"]) + int(reconciliation["already_current"]) < int(
        corpus["eligible_paper_count"]
    ):
        raise RuntimeError("generation reconciliation cannot account for every eligible paper")
    build = rebuild_keyword_index(session)
    health = diagnostics(session)
    metadata = keyword_index_metadata(session) or {}
    completeness = str(build.get("completeness_status") or "")
    if completeness not in {"complete", "fallback_only"}:
        raise RuntimeError(f"temporary keyword index has invalid completeness status: {completeness}")
    if int(build.get("eligible_chunks") or -1) != int(corpus["eligible_chunk_count"]):
        raise RuntimeError("temporary keyword index eligible-chunk count drift")
    if int(build.get("eligible_papers") or -1) != int(corpus["eligible_paper_count"]):
        raise RuntimeError("temporary keyword index eligible-paper count drift")
    if build.get("corpus_snapshot_hash") != corpus["snapshot_hash"]:
        raise RuntimeError("temporary keyword index build used a different corpus snapshot")
    if completeness == "complete":
        if health.get("status") != "ready" or health.get("completeness_status") != "complete":
            raise RuntimeError(f"temporary keyword index failed integrity validation: {health.get('errors')}")
        if int(health.get("keyword_indexed_chunks") or -1) != int(corpus["eligible_chunk_count"]):
            raise RuntimeError("temporary keyword index is incomplete")
        if (metadata.get("corpus") or {}).get("snapshot_hash") != corpus["snapshot_hash"]:
            raise RuntimeError("temporary keyword-index metadata corpus hash mismatch")
    elif health.get("fts_available") is not False:
        raise RuntimeError("fallback-only keyword search is allowed only when FTS5 is unavailable")

    corpus_identity = {
        "identity_contract": "retrieval_source_identity_v2",
        "snapshot_id": corpus["snapshot_id"],
        "snapshot_hash": corpus["snapshot_hash"],
        "eligible_chunk_count": corpus["eligible_chunk_count"],
        "eligible_paper_count": corpus["eligible_paper_count"],
        "technical_selection_predicate": TECHNICAL_SELECTION_PREDICATE,
    }
    index_record = {
        "database_scope": "temporary_copy_only",
        "source": "frozen_technical_eligible_corpus",
        "generation_reconciliation": reconciliation,
        "rebuild_result": {
            key: value
            for key, value in build.items()
            if key != "last_indexed_at"
        },
        "health": {
            key: health.get(key)
            for key in (
                "fts_available",
                "keyword_indexed_chunks",
                "eligible_chunks",
                "eligible_papers",
                "coverage_ratio",
                "corpus_snapshot_id",
                "corpus_snapshot_hash",
                "stored_corpus_snapshot_hash",
                "completeness_status",
                "provider",
                "errors",
                "status",
            )
        },
        "configuration_sha256": metadata.get("configuration_hash"),
    }
    return index_record, corpus_identity


def source_row(session: Any, chunk_model: Any, chunk_id: str) -> Any:
    from sqlmodel import select

    row = session.exec(select(chunk_model).where(chunk_model.chunk_id == chunk_id)).first()
    if row is None:
        raise ValueError(f"missing frozen chunk: {chunk_id}")
    return row


def validate_source_locator(
    session: Any,
    chunk_model: Any,
    locator: dict[str, Any],
    *,
    expected_paper_id: str | None = None,
) -> Any:
    from app.models import Paper

    row = source_row(session, chunk_model, str(locator["chunk_id"]))
    expected = expected_paper_id or locator.get("paper_id")
    if expected and str(row.paper_id) != str(expected):
        raise ValueError(f"source paper mismatch for {locator['chunk_id']}")
    if row.source_hash != locator["source_hash"]:
        raise ValueError(f"source hash mismatch for {locator['chunk_id']}")
    if sha256_bytes(str(row.text or "").encode("utf-8")) != row.source_hash:
        raise ValueError(f"persisted source hash does not match text for {locator['chunk_id']}")
    if normalize_text(locator["anchor"]) not in normalize_text(row.text):
        raise ValueError(f"source anchor not found for {locator['chunk_id']}: {locator['anchor']}")
    for key in ("page_start", "page_end", "section"):
        if key in locator and locator.get(key) != getattr(row, key):
            raise ValueError(f"source locator {key} mismatch for {locator['chunk_id']}")
    paper = session.get(Paper, row.paper_id)
    if paper is None:
        raise ValueError(f"source paper missing for {locator['chunk_id']}")
    extraction_generation = str(getattr(paper, "extraction_generation_id", "") or "")
    if (
        paper.corpus_eligibility_status != "eligible"
        or not extraction_generation
        or not str(getattr(paper, "chunk_generation_id", "") or "")
        or str(getattr(paper, "chunk_extraction_generation_id", "") or "")
        != extraction_generation
        or str(getattr(row, "extraction_generation_id", "") or "") != extraction_generation
    ):
        raise ValueError(
            f"source locator is outside the generation-linked technical corpus: {locator['chunk_id']}"
        )
    return row


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text, flags=re.I)
    text = re.sub(r"(?<![A-Za-z0-9])/(?:home|mnt|tmp)/[^\s\]\[(){}]+", "[REDACTED_LOCAL_PATH]", text)
    return text


def bounded(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", redact_text(value)).strip()[:limit]


def redact_json_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_json_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json_strings(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def build_chunk_hashes(session: Any, chunks: Iterable[Any]) -> dict[str, dict[str, str]]:
    from app.indexing.embedder import chunk_effective_source_hash

    return {
        str(row.chunk_id): {
            "chunk_text_sha256": str(row.source_hash or ""),
            "effective_source_sha256": chunk_effective_source_hash(session, row),
        }
        for row in chunks
    }


def sanitize_citation(
    citation: dict[str, Any],
    source_hashes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    chunk_id = str(citation.get("chunk_id") or "")
    hashes = source_hashes.get(chunk_id, {})
    return {
        "paper_id": citation.get("paper_id"),
        "title": citation.get("title"),
        "chunk_id": chunk_id,
        "chunk_text_sha256": hashes.get("chunk_text_sha256"),
        "effective_source_sha256": hashes.get("effective_source_sha256"),
        "section": citation.get("section"),
        "page_start": citation.get("page_start"),
        "page_end": citation.get("page_end"),
        "score": citation.get("score"),
        "snippet": bounded(citation.get("snippet")),
    }


def sanitize_qa_response(
    case: dict[str, Any],
    response: dict[str, Any],
    source_hashes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    answerability = response.get("answerability") or {}
    citations = [sanitize_citation(item, source_hashes) for item in response.get("citations", [])]
    retrieved = []
    for item in response.get("retrieved_chunks", []):
        chunk_id = str(item.get("chunk_id") or "")
        hashes = source_hashes.get(chunk_id, {})
        retrieved.append(
            {
                "chunk_id": chunk_id,
                "paper_id": item.get("paper_id"),
                "title": item.get("title"),
                "chunk_text_sha256": hashes.get("chunk_text_sha256"),
                "effective_source_sha256": hashes.get("effective_source_sha256"),
                "section": item.get("section"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "scores": item.get("scores", {}),
                "snippet": bounded(item.get("snippet") or item.get("text")),
            }
        )
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "category": case["category"],
        "expected_answerable": case["expected_answerable"],
        "question": case["question"],
        "answer": redact_text(response.get("answer")),
        "provider": response.get("provider"),
        "model": response.get("model"),
        "grounding_status": response.get("grounding_status"),
        "support_status": response.get("support_status"),
        "retrieval_mode": response.get("retrieval_mode"),
        "retrieval_scope": (response.get("retrieval_metadata") or {}).get("retrieval_scope", "technical"),
        "retrieval_metadata": response.get("retrieval_metadata", {}),
        "generation_metadata": response.get("generation_metadata", {}),
        "runtime_provenance": redact_json_strings(response.get("runtime_provenance", {})),
        "answerability": answerability,
        "citations": citations,
        "retrieved_chunks": retrieved,
        "claim_support": redact_json_strings(response.get("claim_support", [])),
        "warnings": redact_json_strings(response.get("warnings", [])),
        "unsupported_claims": redact_json_strings(response.get("unsupported_claims", [])),
        "sanitization": "full source chunk text removed; excerpts capped at 240 characters; response UUID omitted; runtime-provenance timestamp retained",
    }


def versionable_qa_output(output: dict[str, Any]) -> dict[str, Any]:
    """Remove extractive/source text while retaining auditable QA structure."""

    answerability = output.get("answerability") or {}
    structural_answerability = {
        key: answerability.get(key)
        for key in (
            "answerable",
            "reason",
            "query_terms",
            "matched_query_terms",
            "max_query_coverage",
            "minimum_query_coverage",
            "relevant_chunk_ids",
        )
        if key in answerability
    }
    claims = []
    for claim in output.get("claim_support", []):
        claims.append(
            {
                "claim_attestation": text_attestation(claim.get("claim")),
                "classification": claim.get("classification"),
                "cited_chunk_ids": list(claim.get("cited_chunk_ids", [])),
                "supporting_chunk_ids": list(claim.get("supporting_chunk_ids", [])),
                "citation_support": [
                    {
                        key: support.get(key)
                        for key in (
                            "chunk_id",
                            "lexical_overlap",
                            "classification",
                            "entailment_verified",
                        )
                        if key in support
                    }
                    for support in claim.get("citation_support", [])
                ],
                "lexical_overlap": claim.get("lexical_overlap"),
                "entailment_verified": claim.get("entailment_verified", False),
            }
        )
    return {
        key: output.get(key)
        for key in (
            "case_id",
            "split",
            "category",
            "expected_answerable",
            "question",
            "provider",
            "model",
            "grounding_status",
            "support_status",
            "retrieval_mode",
            "retrieval_scope",
            "retrieval_metadata",
            "generation_metadata",
            "runtime_provenance",
        )
    } | {
        "answer_attestation": text_attestation(output.get("answer")),
        "answerability": structural_answerability,
        "citations": [structural_citation(item) for item in output.get("citations", [])],
        "retrieved_chunks": [
            structural_citation(item) for item in output.get("retrieved_chunks", [])
        ],
        "claim_support": claims,
        "warning_attestations": [text_attestation(item) for item in output.get("warnings", [])],
        "unsupported_claim_attestations": [
            text_attestation(item) for item in output.get("unsupported_claims", [])
        ],
        "publication_boundary": "structural_only; rights-sensitive raw text retained outside versionable artifacts",
    }


def point_covered(answer: str, point: dict[str, Any]) -> bool:
    normalized = normalize_text(answer)
    for alternatives in point.get("groups", []):
        if not any(normalize_text(term) in normalized for term in alternatives):
            return False
    return True


def review_qa_case(case: dict[str, Any], output: dict[str, Any], pass_name: str, order: int) -> dict[str, Any]:
    gold = case.get("gold_locator") or {}
    expected_answerable = bool(case["expected_answerable"])
    provider_invoked = output.get("provider") not in {None, "not_invoked"}
    actual_answered = bool(
        provider_invoked
        and output.get("grounding_status") != "unsupported"
        and output.get("citations")
    )
    returned_by_id = {str(item.get("chunk_id") or ""): item for item in output.get("citations", [])}
    citation_links: list[dict[str, Any]] = []
    claims = output.get("claim_support", [])
    for claim_index, claim in enumerate(claims, start=1):
        for chunk_id in claim.get("cited_chunk_ids", []):
            citation = returned_by_id.get(str(chunk_id), {})
            if not expected_answerable:
                judgment = "incorrect"
            elif chunk_id == gold.get("chunk_id"):
                judgment = "correct_exact_gold_locator"
            elif citation.get("paper_id") == gold.get("paper_id"):
                judgment = "partial_same_gold_paper_non_gold_chunk"
            else:
                judgment = "incorrect"
            citation_links.append(
                {
                    "claim_index": claim_index,
                    "chunk_id": chunk_id,
                    "paper_id": citation.get("paper_id"),
                    "judgment": judgment,
                    "entailment_verified": False,
                }
            )
    point_reviews = [
        {"point_id": point["point_id"], "covered": point_covered(str(output.get("answer") or ""), point)}
        for point in case.get("answer_points", [])
    ]
    returned_ids = set(returned_by_id)
    supporting_returned_ids_by_claim = [
        {
            str(chunk_id)
            for chunk_id in claim.get("supporting_chunk_ids", [])
            if str(chunk_id) in returned_ids
        }
        for claim in claims
    ]
    structurally_cited_claims = sum(bool(chunk_ids) for chunk_ids in supporting_returned_ids_by_claim)
    used_ids = set().union(*supporting_returned_ids_by_claim) if supporting_returned_ids_by_claim else set()
    cluster_id = str(gold.get("paper_id") or (case.get("negative_evidence") or {}).get("paper_id") or "")
    if not cluster_id:
        raise ValueError(f"{case['case_id']}: QA cluster identity is missing")
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "cluster_id": cluster_id,
        "review_pass": pass_name,
        "review_order": order,
        "reviewer": REVIEWER,
        "expected_answerable": expected_answerable,
        "actual_answered": actual_answered,
        "correct_selective_decision": actual_answered == expected_answerable,
        "citation_links": citation_links,
        "claim_count": len(claims),
        "structurally_cited_claim_count": structurally_cited_claims,
        "returned_citation_count": len(returned_ids),
        "used_returned_citation_count": len(used_ids),
        "answer_points": point_reviews,
        "boundary": "Exact locator and lexical point checks are AI-silver structural judgments; they do not establish semantic entailment or human usefulness.",
    }


def shuffled_review(
    cases: list[dict[str, Any]],
    outputs_by_id: dict[str, dict[str, Any]],
    pass_name: str,
    reviewer: Callable[[dict[str, Any], dict[str, Any], str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = list(cases)
    random.Random(REVIEW_SEEDS[pass_name]).shuffle(ordered)
    return [reviewer(case, outputs_by_id[_case_id(case)], pass_name, index) for index, case in enumerate(ordered, start=1)]


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("case_id") or case.get("profile_id"))


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def aggregate_qa(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(row["expected_answerable"] and row["actual_answered"] for row in rows)
    fp = sum((not row["expected_answerable"]) and row["actual_answered"] for row in rows)
    fn = sum(row["expected_answerable"] and (not row["actual_answered"]) for row in rows)
    tn = sum((not row["expected_answerable"]) and (not row["actual_answered"]) for row in rows)
    citation_links = [link for row in rows if row["expected_answerable"] for link in row["citation_links"]]
    correct_links = sum(link["judgment"] == "correct_exact_gold_locator" for link in citation_links)
    partial_links = sum(link["judgment"].startswith("partial_") for link in citation_links)
    incorrect_links = len(citation_links) - correct_links - partial_links
    claims = sum(row["claim_count"] for row in rows if row["expected_answerable"])
    cited_claims = sum(row["structurally_cited_claim_count"] for row in rows if row["expected_answerable"])
    returned = sum(row["returned_citation_count"] for row in rows if row["expected_answerable"])
    used = sum(row["used_returned_citation_count"] for row in rows if row["expected_answerable"])
    points = [point for row in rows if row["expected_answerable"] for point in row["answer_points"]]
    covered = sum(point["covered"] for point in points)
    return {
        "case_count": len(rows),
        "counts": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "citation_links": len(citation_links),
            "correct_exact_gold_locator_links": correct_links,
            "partial_same_paper_links": partial_links,
            "incorrect_links": incorrect_links,
            "claim_count": claims,
            "structurally_cited_claim_count": cited_claims,
            "returned_citations": returned,
            "used_returned_citations": used,
            "answer_points": len(points),
            "covered_answer_points": covered,
        },
        "metrics": {
            "answerability_precision": safe_ratio(tp, tp + fp),
            "answerability_recall": safe_ratio(tp, tp + fn),
            "false_positive_rate": safe_ratio(fp, fp + tn),
            "abstention_rate": safe_ratio(fn + tn, len(rows)),
            "abstention_accuracy": safe_ratio(tp + tn, len(rows)),
            "exact_gold_locator_citation_precision": safe_ratio(correct_links, len(citation_links)),
            "citation_completeness": safe_ratio(cited_claims, claims),
            "returned_citation_utilization": safe_ratio(used, returned),
            "answer_point_coverage": safe_ratio(covered, len(points)),
        },
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def bootstrap_metrics(
    rows: list[dict[str, Any]],
    aggregate: Callable[[list[dict[str, Any]]], dict[str, Any]],
    *,
    cluster_key: str,
    unit: str,
    metric_path: str = "metrics",
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cluster bootstrap requires at least one row")
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cluster_id = str(row.get(cluster_key) or "")
        if not cluster_id:
            raise ValueError(f"cluster bootstrap row lacks {cluster_key}")
        clusters.setdefault(cluster_id, []).append(row)
    cluster_ids = sorted(clusters)
    rng = random.Random(BOOTSTRAP_SEED)
    metric_names = list(aggregate(rows)[metric_path])
    replicates: dict[str, list[float]] = {name: [] for name in metric_names}
    for _ in range(BOOTSTRAP_REPLICATES):
        sampled_cluster_ids = [cluster_ids[rng.randrange(len(cluster_ids))] for _ in cluster_ids]
        sample = [row for cluster_id in sampled_cluster_ids for row in clusters[cluster_id]]
        metrics = aggregate(sample)[metric_path]
        for name, value in metrics.items():
            if value is not None and math.isfinite(float(value)):
                replicates[name].append(float(value))
    estimates = aggregate(rows)[metric_path]
    return {
        "method": "cluster_level_percentile_bootstrap",
        "unit": unit,
        "cluster_key": cluster_key,
        "cluster_count": len(cluster_ids),
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "confidence_level": 0.95,
        "label_uncertainty_included": False,
        "corpus_selection_uncertainty_included": False,
        "metrics": {
            name: {
                "estimate": estimates[name],
                "ci_lower": round(percentile(values, 0.025), 6) if values else None,
                "ci_upper": round(percentile(values, 0.975), 6) if values else None,
                "valid_replicates": len(values),
            }
            for name, values in replicates.items()
        },
    }


def review_disagreements(pass1: list[dict[str, Any]], pass2: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    by_id_2 = {_case_id(row): row for row in pass2}
    disagreements: list[dict[str, Any]] = []
    for row1 in pass1:
        row2 = by_id_2[_case_id(row1)]
        differing = [field for field in fields if row1.get(field) != row2.get(field)]
        if differing:
            disagreements.append({"id": _case_id(row1), "differing_fields": differing})
    return {
        "reviewer": REVIEWER,
        "pass_1_seed": REVIEW_SEEDS["pass_1"],
        "pass_2_seed": REVIEW_SEEDS["pass_2"],
        "orders_differ": [_case_id(row) for row in pass1] != [_case_id(row) for row in pass2],
        "same_case_set": {_case_id(row) for row in pass1} == {_case_id(row) for row in pass2},
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "interpretation": "Repeated same-AI procedure under shuffled presentation; not independent or human inter-rater reliability.",
    }


def run_qa(session: Any, chunk_model: Any) -> None:
    from app.intelligence.rag_answerer import ask_question
    from sqlmodel import select

    cases = read_jsonl(QA_PATH)
    for case in cases:
        if case.get("gold_locator"):
            validate_source_locator(session, chunk_model, case["gold_locator"])
        else:
            negative = case.get("negative_evidence") or {}
            validate_source_locator(
                session,
                chunk_model,
                negative["context_locator"],
                expected_paper_id=str(negative["paper_id"]),
            )
    all_chunks = session.exec(select(chunk_model)).all()
    source_hashes = build_chunk_hashes(session, all_chunks)
    review_outputs: list[dict[str, Any]] = []
    versionable_outputs: list[dict[str, Any]] = []
    restricted_outputs: list[dict[str, Any]] = []
    for case in cases:
        response = ask_question(
            session,
            case["question"],
            mode="keyword",
            top_k=5,
            audience="general",
            max_words=180,
            provider_name="offline_extractive",
            persist=False,
            retrieval_scope="technical",
        )
        restricted_outputs.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "case": redact_json_strings(case),
                "response": redact_json_strings(response),
                "restriction": "operator-local rights-sensitive raw output; not for commit or release",
            }
        )
        review_output = sanitize_qa_response(case, response, source_hashes)
        review_outputs.append(review_output)
        versionable_outputs.append(versionable_qa_output(review_output))
    write_jsonl(RESTRICTED_OUTPUT_PATHS["qa_full_raw"], restricted_outputs)
    write_jsonl(OUTPUT_PATHS["qa_raw"], versionable_outputs)
    outputs_by_id = {row["case_id"]: row for row in review_outputs}
    pass1 = shuffled_review(cases, outputs_by_id, "pass_1", review_qa_case)
    pass2 = shuffled_review(cases, outputs_by_id, "pass_2", review_qa_case)
    write_jsonl(OUTPUT_PATHS["qa_pass1"], pass1)
    write_jsonl(OUTPUT_PATHS["qa_pass2"], pass2)
    disagreements = review_disagreements(
        pass1,
        pass2,
        [
            "actual_answered",
            "correct_selective_decision",
            "citation_links",
            "answer_points",
            "claim_count",
            "structurally_cited_claim_count",
            "returned_citation_count",
            "used_returned_citation_count",
        ],
    )
    write_json(OUTPUT_PATHS["qa_disagreements"], disagreements)
    by_split = {
        split: aggregate_qa([row for row in pass1 if row["split"] == split])
        for split in ("dev", "test")
    }
    by_split["all"] = aggregate_qa(pass1)
    test_rows = [row for row in pass1 if row["split"] == "test"]
    metrics = {
        "evaluation_id": "qa-selective-response-v2",
        "status": "completed",
        "reviewer": REVIEWER,
        "retrieval_scope": "technical",
        "threshold_tuned_on_v2": False,
        "metric_boundaries": {
            "exact_gold_locator_citation_precision": "Exact predeclared chunk matches divided by structurally used claim-to-citation links. Same-paper non-gold links are partial and not counted correct. This is AI-silver locator precision, not entailment.",
            "citation_completeness": "Claims with at least one structurally resolved returned citation divided by reviewable returned claims.",
            "returned_citation_utilization": "Distinct returned citations used by claim markers divided by distinct returned citations.",
            "answer_point_coverage": "Predeclared lexical answer points found in the returned answer; abstained answerable cases contribute zero covered points.",
        },
        "by_split": by_split,
        "test_bootstrap_95_ci": bootstrap_metrics(
            test_rows,
            aggregate_qa,
            cluster_key="cluster_id",
            unit="named_source_paper",
        ),
        "repeatability": disagreements,
        "limitations": [
            "The 18-case set is small and AI-authored; it is AI-silver, not human validated.",
            "Exact locator correctness and lexical answer-point coverage do not establish semantic entailment.",
            "Confidence intervals exclude label, corpus-selection, and model-state uncertainty.",
            "Technical retrieval scope does not establish public eligibility or public behavior.",
        ],
    }
    write_json(OUTPUT_PATHS["qa_metrics"], metrics)
    print(f"Ask evaluation complete: {len(cases)} frozen cases", flush=True)


def finder_request(case: dict[str, Any], request_model: Any) -> Any:
    return request_model(
        interests=case["interests"],
        skills=case["skills"],
        available_time=case["available_time"],
        project_type=case["project_type"],
        data_constraints=case["data_constraints"],
        preferred_difficulty=case["preferred_difficulty"],
        preferred_topics=case["preferred_topics"],
        top_k=3,
        retrieval_mode="keyword",
        provider="offline_deterministic",
    )


def sanitize_finder(
    case: dict[str, Any],
    retrieval: dict[str, Any],
    baseline: dict[str, Any],
    full: dict[str, Any],
    source_hashes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    baseline_papers = []
    for paper in baseline.get("papers", []):
        clean = {key: value for key, value in paper.items() if key != "passages"}
        clean["passages"] = [sanitize_citation(item, source_hashes) for item in paper.get("passages", [])]
        baseline_papers.append(clean)
    full_recommendations = []
    for recommendation in full.get("recommendations", []):
        clean = redact_json_strings(dict(recommendation))
        clean["citations"] = [sanitize_citation(item, source_hashes) for item in recommendation.get("citations", [])]
        clean["source_supported_facts"] = [
            {**fact, "snippet": bounded(fact.get("snippet")), "claim": bounded(fact.get("claim"))}
            for fact in recommendation.get("source_supported_facts", [])
        ]
        full_recommendations.append(clean)
    paired_pool = []
    for item in retrieval.get("results", []):
        chunk_id = str(item.get("chunk_id") or "")
        hashes = source_hashes.get(chunk_id, {})
        paired_pool.append(
            {
                "chunk_id": chunk_id,
                "paper_id": str(item.get("paper_id") or ""),
                "chunk_text_sha256": hashes.get("chunk_text_sha256"),
                "effective_source_sha256": hashes.get("effective_source_sha256"),
                "scores": item.get("scores", {}),
            }
        )
    return {
        "profile_id": case["profile_id"],
        "split": case["split"],
        "constraint_pair": case.get("constraint_pair"),
        "gold_paper_id": case["gold_paper_id"],
        "request": {
            key: case[key]
            for key in (
                "interests",
                "skills",
                "available_time",
                "project_type",
                "data_constraints",
                "preferred_difficulty",
                "preferred_topics",
            )
        },
        "retrieval_scope": "technical",
        "paired_retrieval": {
            "same_frozen_response_supplied_to_evidence_only_and_full": True,
            "expanded_query": retrieval.get("expanded_query"),
            "retrieval_mode": retrieval.get("mode"),
            "retrieval_strategy": retrieval.get("retrieval_strategy"),
            "retriever_config": retrieval.get("retriever_config", {}),
            "warnings": retrieval.get("warnings", []),
            "result_count": len(paired_pool),
            "result_locators": paired_pool,
            "result_pool_sha256": sha256_bytes(canonical_json(paired_pool).encode("utf-8")),
        },
        "evidence_only": {**baseline, "papers": baseline_papers},
        "full_finder": {
            "grounding_status": full.get("grounding_status"),
            "support_status": "support_unverified" if full.get("grounding_status") == "partial" else "unsupported",
            "provider": full.get("provider"),
            "model": full.get("model"),
            "answerability": full.get("answerability", {}),
            "runtime_provenance": redact_json_strings(full.get("runtime_provenance", {})),
            "recommendations": full_recommendations,
            "warnings": full.get("warnings", []),
        },
        "sanitization": "source excerpts capped at 240 characters; response UUID omitted; runtime-provenance timestamp retained",
    }


def _finder_skill_tokens(value: str) -> set[str]:
    stopwords = {
        "about", "after", "also", "and", "are", "based", "but", "can", "data", "for",
        "from", "has", "have", "into", "its", "may", "not", "paper", "papers", "project",
        "research", "student", "that", "the", "their", "this", "with",
    }
    return {
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9]+", value)
        if len(token) > 1 and token.lower() not in stopwords
    }


def _expected_skill_gap(student_skills: list[str], required_skills: list[str]) -> list[str]:
    student_blob = " ".join(student_skills).lower()
    student_tokens = _finder_skill_tokens(student_blob)
    gaps: list[str] = []
    for required in required_skills:
        required_tokens = _finder_skill_tokens(required)
        covered = bool(
            required.lower() in student_blob
            or (required_tokens and required_tokens.intersection(student_tokens))
        )
        if not covered:
            gaps.append(required)
    return gaps


def finder_profile_constraint_checks(
    case: dict[str, Any],
    recommendation: dict[str, Any],
) -> dict[str, bool]:
    """Check every profile input represented by the deterministic output contract."""

    constraints = recommendation.get("profile_constraints") or {}
    interest_parts = [
        part.strip() for part in re.split(r"[,;/]", str(case.get("interests") or "")) if part.strip()
    ]
    primary_words = re.sub(r"\s+", " ", interest_parts[0] if interest_parts else "research").split()
    primary_interest = " ".join(primary_words[:5]).rstrip(" ,;:")
    if len(primary_words) > 5:
        primary_interest += "..."
    topic_text = ", ".join(case.get("preferred_topics") or []) or str(case.get("interests") or "")
    required_skills = [str(value) for value in recommendation.get("required_skills", [])]
    observed_gap = [str(value) for value in recommendation.get("skills_gap", [])]
    checks = {
        "classification": constraints.get("classification")
        == "student_supplied_preferences_not_paper_facts",
        "available_time": constraints.get("available_time") == case.get("available_time"),
        "data_constraints": constraints.get("data_constraints") == case.get("data_constraints"),
        "preferred_difficulty": constraints.get("preferred_difficulty")
        == case.get("preferred_difficulty"),
        "project_type": normalize_text(str(case.get("project_type") or ""))
        in normalize_text(str(recommendation.get("extension_summary") or "")),
        "primary_interest": normalize_text(primary_interest)
        in normalize_text(str(recommendation.get("extension_title") or "")),
        "preferred_topics_or_interests": normalize_text(topic_text)
        in normalize_text(str(recommendation.get("why_it_fits_student") or "")),
        "skills_and_gap": bool(required_skills)
        and observed_gap
        == _expected_skill_gap([str(value) for value in case.get("skills", [])], required_skills),
    }
    return checks


def _attest_text_list(values: Iterable[Any]) -> dict[str, Any]:
    normalized = [redact_text(value) for value in values]
    return {
        "count": len(normalized),
        "canonical_sha256": sha256_bytes(canonical_json(normalized).encode("utf-8")),
    }


def versionable_finder_output(output: dict[str, Any]) -> dict[str, Any]:
    """Project Finder output to structural evidence without recommendation prose."""

    evidence_only = output.get("evidence_only") or {}
    baseline_papers = [
        {
            "rank": paper.get("rank"),
            "paper_id": paper.get("paper_id"),
            "year": paper.get("year"),
            "retrieval_score": paper.get("retrieval_score"),
            "paper_title_attestation": text_attestation(paper.get("paper_title")),
            "author_list_attestation": _attest_text_list(paper.get("authors", [])),
            "passages": [structural_citation(item) for item in paper.get("passages", [])],
        }
        for paper in evidence_only.get("papers", [])
    ]
    recommendations: list[dict[str, Any]] = []
    text_fields = (
        "paper_title",
        "paper_focus",
        "extension_title",
        "extension_summary",
        "why_it_fits_student",
        "mvp_scope",
        "data_required",
        "evaluation_plan",
        "risk_basis",
    )
    for recommendation in (output.get("full_finder") or {}).get("recommendations", []):
        gap = recommendation.get("identified_gap") or {}
        facts = [
            {
                "claim_attestation": text_attestation(fact.get("claim")),
                "snippet_attestation": text_attestation(fact.get("snippet")),
                "chunk_id": fact.get("chunk_id"),
                "page_start": fact.get("page_start"),
                "page_end": fact.get("page_end"),
                "support_status": fact.get("support_status"),
                "entailment_verified": fact.get("entailment_verified", False),
            }
            for fact in recommendation.get("source_supported_facts", [])
        ]
        recommendations.append(
            {
                key: recommendation.get(key)
                for key in (
                    "rank",
                    "paper_id",
                    "year",
                    "fit_score",
                    "score_breakdown",
                    "data_availability",
                    "difficulty",
                    "risk_level",
                    "implementation_time",
                    "profile_constraints",
                    "mvp_scope_basis",
                    "evaluation_plan_basis",
                )
            }
            | {
                "generated_text_attestations": {
                    f"{field}_attestation": text_attestation(recommendation.get(field))
                    for field in text_fields
                },
                "author_list_attestation": _attest_text_list(recommendation.get("authors", [])),
                "source_supported_facts": facts,
                "identified_gap": {
                    "text_attestation": text_attestation(gap.get("text")),
                    "support_status": gap.get("support_status"),
                    "source_chunk_ids": list(gap.get("source_chunk_ids", [])),
                },
                "data_availability_evidence": {
                    "status": (recommendation.get("data_availability_evidence") or {}).get("status"),
                    "classification": (
                        recommendation.get("data_availability_evidence") or {}
                    ).get("classification"),
                    "source_chunk_ids": list(
                        (recommendation.get("data_availability_evidence") or {}).get(
                            "source_chunk_ids", []
                        )
                    ),
                    "matched_term_attestation": _attest_text_list(
                        (recommendation.get("data_availability_evidence") or {}).get(
                            "matched_terms", []
                        )
                    ),
                },
                "difficulty_basis": {
                    "value": (recommendation.get("difficulty_basis") or {}).get("value"),
                    "classification": (recommendation.get("difficulty_basis") or {}).get(
                        "classification"
                    ),
                    "source_chunk_ids": list(
                        (recommendation.get("difficulty_basis") or {}).get(
                            "source_chunk_ids", []
                        )
                    ),
                    "matched_term_attestation": _attest_text_list(
                        (recommendation.get("difficulty_basis") or {}).get("matched_terms", [])
                    ),
                },
                "implementation_time_basis": {
                    "classification": (
                        recommendation.get("implementation_time_basis") or {}
                    ).get("classification"),
                    "reason_attestation": text_attestation(
                        (recommendation.get("implementation_time_basis") or {}).get("reason")
                    ),
                },
                "stretch_goal_attestation": _attest_text_list(recommendation.get("stretch_goals", [])),
                "required_skill_attestation": _attest_text_list(recommendation.get("required_skills", [])),
                "skills_gap_attestation": _attest_text_list(recommendation.get("skills_gap", [])),
                "related_paper_ids": [
                    str(item.get("paper_id") or "") for item in recommendation.get("related_papers", [])
                ],
                "potential_researcher_fit_count": len(
                    recommendation.get("potential_researcher_fit", [])
                ),
                "citations": [
                    structural_citation(item) for item in recommendation.get("citations", [])
                ],
                "warning_attestation": _attest_text_list(recommendation.get("warnings", [])),
            }
        )
    full = output.get("full_finder") or {}
    return {
        "profile_id": output.get("profile_id"),
        "split": output.get("split"),
        "constraint_pair": output.get("constraint_pair"),
        "gold_paper_id": output.get("gold_paper_id"),
        "request": output.get("request"),
        "retrieval_scope": output.get("retrieval_scope"),
        "paired_retrieval": output.get("paired_retrieval"),
        "evidence_only": {
            "output_mode": evidence_only.get("output_mode"),
            "retrieval_mode": evidence_only.get("retrieval_mode"),
            "vector_provider": evidence_only.get("vector_provider"),
            "top_k": evidence_only.get("top_k"),
            "query_attestation": text_attestation(evidence_only.get("query")),
            "expanded_query_attestation": text_attestation(evidence_only.get("expanded_query")),
            "papers": baseline_papers,
            "warning_attestation": _attest_text_list(evidence_only.get("warnings", [])),
            "disclaimer_attestation": text_attestation(evidence_only.get("disclaimer")),
        },
        "full_finder": {
            "grounding_status": full.get("grounding_status"),
            "support_status": full.get("support_status"),
            "provider": full.get("provider"),
            "model": full.get("model"),
            "answerability": full.get("answerability", {}),
            "runtime_provenance": full.get("runtime_provenance", {}),
            "recommendations": recommendations,
            "warning_attestation": _attest_text_list(full.get("warnings", [])),
        },
        "publication_boundary": "structural_only; rights-sensitive raw text retained outside versionable artifacts",
    }


def paper_rank(paper_ids: list[str], gold: str) -> int | None:
    try:
        return paper_ids.index(gold) + 1
    except ValueError:
        return None


def review_finder_case(case: dict[str, Any], output: dict[str, Any], pass_name: str, order: int) -> dict[str, Any]:
    baseline_ids = [str(item.get("paper_id") or "") for item in output["evidence_only"].get("papers", [])]
    recommendations = output["full_finder"].get("recommendations", [])
    full_ids = [str(item.get("paper_id") or "") for item in recommendations]
    gold = case["gold_paper_id"]
    candidate_checks: list[dict[str, Any]] = []
    for recommendation in recommendations:
        paper_id = str(recommendation.get("paper_id") or "")
        paper_title = normalize_text(str(recommendation.get("paper_title") or ""))
        mvp = normalize_text(str(recommendation.get("mvp_scope") or ""))
        evaluation = normalize_text(str(recommendation.get("evaluation_plan") or ""))
        cited_papers = {str(citation.get("paper_id") or "") for citation in recommendation.get("citations", [])}
        facts = recommendation.get("source_supported_facts", [])
        source_fact_boundary = all(
            fact.get("support_status") == "support_unverified" and fact.get("entailment_verified") is False
            for fact in facts
        )
        separation = bool(
            source_fact_boundary
            and (recommendation.get("mvp_scope_basis") or {}).get("classification") == "system_suggestion"
            and (recommendation.get("evaluation_plan_basis") or {}).get("classification") == "system_suggestion"
            and (recommendation.get("identified_gap") or {}).get("support_status")
            in {"source_phrase_unverified", "inferred_from_paper", "not_found"}
        )
        constraint_checks = finder_profile_constraint_checks(case, recommendation)
        candidate_checks.append(
            {
                "paper_id": paper_id,
                "candidate_specific_template_conformance": bool(
                    paper_title and paper_title in mvp and paper_title in evaluation and cited_papers == {paper_id}
                ),
                "source_fact_suggestion_separation": separation,
                "implementation_time_unknown": bool(
                    recommendation.get("implementation_time") == "unknown"
                    and (recommendation.get("implementation_time_basis") or {}).get("classification") == "unknown"
                ),
                "profile_constraint_checks": constraint_checks,
                "full_profile_constraint_contract_fidelity": all(constraint_checks.values()),
                "usefulness_feasibility_label": "ai_proxy_not_human_validated",
            }
        )
    profile_fidelity = bool(candidate_checks) and all(
        item["full_profile_constraint_contract_fidelity"] for item in candidate_checks
    )
    baseline_rank = paper_rank(baseline_ids, gold)
    full_rank = paper_rank(full_ids, gold)
    return {
        "profile_id": case["profile_id"],
        "split": case["split"],
        "cluster_id": str(case.get("constraint_pair") or case["profile_id"]),
        "constraint_pair": case.get("constraint_pair"),
        "input_available_time": case["available_time"],
        "input_preferred_difficulty": case["preferred_difficulty"],
        "review_pass": pass_name,
        "review_order": order,
        "reviewer": REVIEWER,
        "gold_paper_id": gold,
        "evidence_only_gold_rank": baseline_rank,
        "full_finder_gold_rank": full_rank,
        "evidence_only_hit_at_3": baseline_rank is not None and baseline_rank <= 3,
        "full_finder_hit_at_3": full_rank is not None and full_rank <= 3,
        "evidence_only_ranked_paper_ids": baseline_ids,
        "full_finder_ranked_paper_ids": full_ids,
        "candidate_checks": candidate_checks,
        "candidate_specific_template_conformance_pass": bool(candidate_checks)
        and all(item["candidate_specific_template_conformance"] for item in candidate_checks),
        "source_fact_suggestion_separation_pass": bool(candidate_checks) and all(item["source_fact_suggestion_separation"] for item in candidate_checks),
        "unknown_implementation_time_retained": bool(candidate_checks) and all(item["implementation_time_unknown"] for item in candidate_checks),
        "full_profile_constraint_contract_fidelity": profile_fidelity,
        "boundary": "Relevance, candidate specificity, usefulness, and feasibility are AI proxy judgments on synthetic profiles, not student or supervisor validation.",
    }


def aggregate_finder(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    baseline_hits = sum(row["evidence_only_hit_at_3"] for row in rows)
    full_hits = sum(row["full_finder_hit_at_3"] for row in rows)
    baseline_rr = sum(1 / row["evidence_only_gold_rank"] if row["evidence_only_gold_rank"] else 0 for row in rows)
    full_rr = sum(1 / row["full_finder_gold_rank"] if row["full_finder_gold_rank"] else 0 for row in rows)
    return {
        "profile_count": count,
        "counts": {"evidence_only_hits_at_3": baseline_hits, "full_finder_hits_at_3": full_hits},
        "metrics": {
            "evidence_only_hit_at_3": safe_ratio(baseline_hits, count),
            "full_finder_hit_at_3": safe_ratio(full_hits, count),
            "paired_hit_at_3_delta": round((full_hits - baseline_hits) / count, 6) if count else None,
            "evidence_only_mrr": round(baseline_rr / count, 6) if count else None,
            "full_finder_mrr": round(full_rr / count, 6) if count else None,
            "paired_mrr_delta": round((full_rr - baseline_rr) / count, 6) if count else None,
            "candidate_specific_template_conformance_rate": safe_ratio(
                sum(row["candidate_specific_template_conformance_pass"] for row in rows), count
            ),
            "source_fact_suggestion_separation_rate": safe_ratio(
                sum(row["source_fact_suggestion_separation_pass"] for row in rows), count
            ),
            "unknown_implementation_time_retention_rate": safe_ratio(
                sum(row["unknown_implementation_time_retained"] for row in rows), count
            ),
            "full_profile_constraint_contract_fidelity_rate": safe_ratio(
                sum(row["full_profile_constraint_contract_fidelity"] for row in rows), count
            ),
        },
    }


def run_finder(session: Any, chunk_model: Any) -> None:
    from app.indexing.retriever import retrieve
    from app.intelligence.extension_recommender import (
        DEFAULT_MODEL,
        DEFAULT_PROVIDER,
        SCORE_WEIGHTS,
        ExtensionFinderRequest,
        build_retrieval_query,
        evidence_only_baseline,
        recommend_extensions,
    )
    from sqlmodel import select

    cases = read_jsonl(FINDER_PATH)
    if SCORE_WEIGHTS != FINDER_SCORE_WEIGHTS:
        raise RuntimeError("backend Finder score weights drift from the frozen v2 protocol")
    if (DEFAULT_PROVIDER, DEFAULT_MODEL) != ("offline_deterministic", "template-recommender-v1"):
        raise RuntimeError("backend Finder provider/model drift from the frozen v2 protocol")
    for case in cases:
        validate_source_locator(session, chunk_model, case["source_locator"])
    all_chunks = session.exec(select(chunk_model)).all()
    source_hashes = build_chunk_hashes(session, all_chunks)
    review_outputs: list[dict[str, Any]] = []
    versionable_outputs: list[dict[str, Any]] = []
    restricted_outputs: list[dict[str, Any]] = []
    for case in cases:
        request = finder_request(case, ExtensionFinderRequest)
        retrieval = retrieve(
            session,
            build_retrieval_query(request),
            mode=request.retrieval_mode,
            top_k=max(request.top_k * 6, request.top_k),
            scope="technical",
        )
        baseline = evidence_only_baseline(
            session,
            request,
            retrieval_response=retrieval,
            retrieval_scope="technical",
        )
        full = recommend_extensions(
            session,
            request,
            persist=False,
            score_weights=FINDER_SCORE_WEIGHTS,
            retrieval_response=retrieval,
            retrieval_scope="technical",
        )
        restricted_outputs.append(
            {
                "profile_id": case["profile_id"],
                "split": case["split"],
                "case": redact_json_strings(case),
                "retrieval": redact_json_strings(retrieval),
                "evidence_only": redact_json_strings(baseline),
                "full_finder": redact_json_strings(full),
                "restriction": "operator-local rights-sensitive raw output; not for commit or release",
            }
        )
        review_output = sanitize_finder(case, retrieval, baseline, full, source_hashes)
        review_outputs.append(review_output)
        versionable_outputs.append(versionable_finder_output(review_output))
    write_jsonl(RESTRICTED_OUTPUT_PATHS["finder_full_raw"], restricted_outputs)
    write_jsonl(OUTPUT_PATHS["finder_raw"], versionable_outputs)
    outputs_by_id = {row["profile_id"]: row for row in review_outputs}
    pass1 = shuffled_review(cases, outputs_by_id, "pass_1", review_finder_case)
    pass2 = shuffled_review(cases, outputs_by_id, "pass_2", review_finder_case)
    write_jsonl(OUTPUT_PATHS["finder_pass1"], pass1)
    write_jsonl(OUTPUT_PATHS["finder_pass2"], pass2)
    disagreements = review_disagreements(
        pass1,
        pass2,
        [
            "evidence_only_gold_rank",
            "full_finder_gold_rank",
            "candidate_checks",
            "candidate_specific_template_conformance_pass",
            "source_fact_suggestion_separation_pass",
            "unknown_implementation_time_retained",
            "full_profile_constraint_contract_fidelity",
        ],
    )
    write_json(OUTPUT_PATHS["finder_disagreements"], disagreements)
    by_split = {
        split: aggregate_finder([row for row in pass1 if row["split"] == split])
        for split in ("dev", "test", "sensitivity")
    }
    by_split["primary_dev_and_test"] = aggregate_finder(
        [row for row in pass1 if row["split"] in {"dev", "test"}]
    )
    by_split["all_including_sensitivity"] = aggregate_finder(pass1)
    test_rows = [row for row in pass1 if row["split"] == "test"]
    pairs: dict[str, list[dict[str, Any]]] = {}
    for row in pass1:
        if row.get("constraint_pair"):
            pairs.setdefault(str(row["constraint_pair"]), []).append(row)
    constraint_checks = {
        name: {
            "profile_ids": sorted(row["profile_id"] for row in rows),
            "input_available_times": sorted({row["input_available_time"] for row in rows}),
            "input_preferred_difficulties": sorted({row["input_preferred_difficulty"] for row in rows}),
            "evidence_only_rankings": {
                row["profile_id"]: row["evidence_only_ranked_paper_ids"] for row in rows
            },
            "full_finder_rankings": {
                row["profile_id"]: row["full_finder_ranked_paper_ids"] for row in rows
            },
            "full_ranking_changed_across_constraints": len(
                {tuple(row["full_finder_ranked_paper_ids"]) for row in rows}
            )
            > 1,
            "all_profiles_satisfy_full_constraint_contract": all(
                row["full_profile_constraint_contract_fidelity"] for row in rows
            ),
            "all_implementation_times_remain_unknown": all(row["unknown_implementation_time_retained"] for row in rows),
            "interpretation": "The system preserves supplied constraints but does not convert available time into a paper-supported feasibility fact.",
        }
        for name, rows in pairs.items()
    }
    metrics = {
        "evaluation_id": "finder-proxy-v2",
        "status": "completed",
        "reviewer": REVIEWER,
        "retrieval_scope": "technical",
        "by_split": by_split,
        "test_bootstrap_95_ci": bootstrap_metrics(
            test_rows,
            aggregate_finder,
            cluster_key="cluster_id",
            unit="profile_family",
        ),
        "constraint_variation": constraint_checks,
        "repeatability": disagreements,
        "metric_boundaries": {
            "candidate_specific_template_conformance_rate": "Checks that deterministic templates name and cite only their current candidate. It is a contract test, not independent specificity or usefulness evidence.",
            "full_profile_constraint_contract_fidelity_rate": "Checks deterministic propagation of interests, skills/gaps, available time, project type, data constraints, preferred difficulty, and preferred topics. It does not establish practical feasibility or human usefulness.",
            "gold_paper_hit_at_3_and_mrr": "Paper lookup on source-derived need profiles that avoid copying titles. A hit does not validate the generated project or its feasibility.",
        },
        "null_result_policy": "Paired deltas are reported with their sign and interval; null or negative findings are not suppressed.",
        "limitations": [
            "The ten profiles are synthetic and AI-authored, not completed by students.",
            "Usefulness and feasibility labels are same-AI proxy judgments, not student or supervisor validation.",
            "Candidate-specific template conformance is mechanically encouraged by the deterministic template and is not an independent quality judgment.",
            "A gold-title hit does not establish novelty, deliverability, data access, ethics approval, or supervisor fit.",
            "Confidence intervals exclude label, corpus-selection, and reviewer uncertainty.",
            "The paired constraint-sensitivity profile is excluded from the primary held-out estimate and reported only as sensitivity evidence.",
            "Technical retrieval scope does not validate public recommendations.",
        ],
    }
    write_json(OUTPUT_PATHS["finder_metrics"], metrics)
    print(f"Finder evaluation complete: {len(cases)} frozen profiles", flush=True)


def topic_aggregate(rows: list[dict[str, Any]], vocabulary: list[str]) -> dict[str, Any]:
    per_label: dict[str, Any] = {}
    total_matched = total_missed = 0
    for label in vocabulary:
        matched_ids = sorted(
            row["case_id"]
            for row in rows
            if label in row["gold_labels"] and label in row["predicted_labels"]
        )
        unadjudicated_ids = sorted(
            row["case_id"]
            for row in rows
            if label not in row["gold_labels"] and label in row["predicted_labels"]
        )
        missed_ids = sorted(
            row["case_id"]
            for row in rows
            if label in row["gold_labels"] and label not in row["predicted_labels"]
        )
        support = sum(label in row["gold_labels"] for row in rows)
        predicted_support = sum(label in row["predicted_labels"] for row in rows)
        matched, missed = len(matched_ids), len(missed_ids)
        total_matched += matched
        total_missed += missed
        per_label[label] = {
            "known_positive_support": support,
            "predicted_support": predicted_support,
            "matched_known_positive_count": matched,
            "missed_known_positive_count": missed,
            "known_positive_recall": safe_ratio(matched, matched + missed),
            "matched_known_positive_case_ids": matched_ids,
            "missed_known_positive_case_ids": missed_ids,
            "unadjudicated_prediction_case_ids": unadjudicated_ids,
            "unadjudicated_predictions_are_not_false_positives": True,
        }
    total_predictions = sum(len(set(row["predicted_labels"])) for row in rows)
    unadjudicated_predictions = sum(
        len(set(row["predicted_labels"]) - set(row["gold_labels"])) for row in rows
    )
    return {
        "case_count": len(rows),
        "vocabulary_size": len(vocabulary),
        "label_scope": "positive_only_not_exhaustive_closed_world",
        "known_positive_micro": {
            "matched": total_matched,
            "missed": total_missed,
            "recall": safe_ratio(total_matched, total_matched + total_missed),
        },
        "known_positive_case_coverage_rate": safe_ratio(
            sum(set(row["gold_labels"]).issubset(set(row["predicted_labels"])) for row in rows),
            len(rows),
        ),
        "unadjudicated_predictions": {
            "count": unadjudicated_predictions,
            "total_predictions": total_predictions,
            "share": safe_ratio(unadjudicated_predictions, total_predictions),
            "false_positive_interpretation_permitted": False,
        },
        "per_label": per_label,
    }


def topic_bootstrap_aggregate(rows: list[dict[str, Any]], vocabulary: list[str]) -> dict[str, Any]:
    aggregate = topic_aggregate(rows, vocabulary)
    return {
        "metrics": {
            "known_positive_micro_recall": aggregate["known_positive_micro"]["recall"],
            "known_positive_case_coverage_rate": aggregate[
                "known_positive_case_coverage_rate"
            ],
            "unadjudicated_prediction_share": aggregate["unadjudicated_predictions"]["share"],
        }
    }


def versionable_topic_output(output: dict[str, Any]) -> dict[str, Any]:
    """Remove source evidence text while retaining topic labels and locators."""

    source = output.get("source_locator") or {}
    return {
        "case_id": output.get("case_id"),
        "split": output.get("split"),
        "cluster_id": output.get("cluster_id"),
        "paper_id": output.get("paper_id"),
        "source_locator": {
            key: source.get(key)
            for key in (
                "chunk_id",
                "paper_id",
                "chunk_text_sha256",
                "effective_source_sha256",
            )
        }
        | {"anchor_attestation": text_attestation(source.get("anchor"))},
        "gold_labels": output.get("gold_labels", []),
        "predicted_labels": output.get("predicted_labels", []),
        "predictions": [
            {
                "label": prediction.get("label"),
                "score": prediction.get("score"),
                "evidence": [
                    {
                        **{key: value for key, value in evidence.items() if key != "text"},
                        "text_attestation": text_attestation(evidence.get("text")),
                    }
                    for evidence in prediction.get("evidence", [])
                ],
            }
            for prediction in output.get("predictions", [])
        ],
        "reviewer": output.get("reviewer"),
        "scope": output.get("scope"),
        "publication_boundary": "structural_only; rights-sensitive raw text retained outside versionable artifacts",
    }


def run_topics(session: Any, chunk_model: Any, paper_model: Any) -> None:
    from app.intelligence.topic_explorer import TOPIC_RULES, topic_candidates_for_paper

    cases = read_jsonl(TOPIC_PATH)
    outputs: list[dict[str, Any]] = []
    for case in cases:
        source = validate_source_locator(session, chunk_model, case["source_locator"])
        source_hashes = build_chunk_hashes(session, [source])[str(source.chunk_id)]
        paper = session.get(paper_model, case["paper_id"])
        if paper is None:
            raise ValueError(f"missing topic paper: {case['paper_id']}")
        candidates = topic_candidates_for_paper(session, paper)
        # Match the production explorer's exact eight-label projection; do not
        # add an evaluation-only secondary ordering or threshold.
        ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:8]
        predicted = [item.normalized_name for item in ranked] or ["other/unknown"]
        outputs.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "cluster_id": case["paper_id"],
                "paper_id": case["paper_id"],
                "source_locator": {
                    "chunk_id": source.chunk_id,
                    "paper_id": source.paper_id,
                    "chunk_text_sha256": source_hashes["chunk_text_sha256"],
                    "effective_source_sha256": source_hashes["effective_source_sha256"],
                    "anchor": bounded(case["source_locator"].get("anchor")),
                },
                "gold_labels": sorted(case["gold_labels"]),
                "predicted_labels": predicted,
                "predictions": [
                    {
                        "label": item.normalized_name,
                        "score": round(float(item.score), 4),
                        "evidence": [
                            {
                                **{key: value for key, value in evidence.items() if key != "text"},
                                "text": bounded(evidence.get("text")),
                            }
                            for evidence in item.evidence[:6]
                        ],
                    }
                    for item in ranked
                ],
                "reviewer": REVIEWER,
                "scope": "technical",
            }
        )
    write_jsonl(
        RESTRICTED_OUTPUT_PATHS["topic_full_raw"],
        [
            {
                **output,
                "restriction": "operator-local rights-sensitive raw output; not for commit or release",
            }
            for output in outputs
        ],
    )
    write_jsonl(
        OUTPUT_PATHS["topic_predictions"],
        [versionable_topic_output(output) for output in outputs],
    )
    vocabulary = sorted({label for label, _terms in TOPIC_RULES} | {"other/unknown"})
    by_split = {
        split: topic_aggregate([row for row in outputs if row["split"] == split], vocabulary)
        for split in ("dev", "test")
    }
    by_split["all"] = topic_aggregate(outputs, vocabulary)
    test_rows = [row for row in outputs if row["split"] == "test"]
    metrics = {
        "evaluation_id": "topic-source-labels-v2",
        "status": "completed",
        "reviewer": REVIEWER,
        "retrieval_scope": "technical",
        "controlled_vocabulary": vocabulary,
        "by_split": by_split,
        "test_bootstrap_95_ci": bootstrap_metrics(
            test_rows,
            lambda sampled: topic_bootstrap_aggregate(sampled, vocabulary),
            cluster_key="cluster_id",
            unit="paper",
        ),
        "public_validation_conclusion": "No public topic/author validation is established. The run uses 12 AI-silver technical-corpus source cases and does not exercise public publication gating or author identity quality.",
        "metric_boundaries": {
            "known_positive_micro_recall": "Fraction of predeclared source-backed positive labels retrieved. The label set is not exhaustive.",
            "known_positive_case_coverage_rate": "Fraction of cases for which every listed known-positive label was retrieved; additional predictions are unadjudicated.",
            "unadjudicated_prediction_share": "Predictions outside the positive-only label set divided by all predictions. This is an annotation-coverage diagnostic, not a false-positive rate.",
            "precision_f1_exact_match": "Not estimated because unlisted labels were not exhaustively adjudicated as negative.",
        },
        "limitations": [
            "Listed known-positive labels are AI-silver and source-derived, not human domain annotations.",
            "Labels are positive-only, not exhaustive closed-world gold; precision, F1, exact match, and false-positive counts are intentionally not reported.",
            "Many labels have zero or one positive test example; per-label misses and support must be read directly.",
            "No claim about public topic precision, author expertise, or public eligibility is supported.",
        ],
    }
    write_json(OUTPUT_PATHS["topic_metrics"], metrics)
    print(f"Topic evaluation complete: {len(cases)} source cases", flush=True)


def levenshtein(left: Sequence[Any], right: Sequence[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            insert = current[right_index - 1] + 1
            delete = previous[right_index] + 1
            replace = previous[right_index - 1] + (left_item != right_item)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def run_ocr() -> None:
    import fitz
    from app.ingestion.ocr import (
        TesseractOCRProvider,
        deterministic_ocr_configuration,
    )
    from app.ingestion.pdf_parser import extract_pdf_text

    gold = json.loads(OCR_GOLD_PATH.read_text(encoding="utf-8"))
    document = fitz.open(OCR_PDF_PATH)
    try:
        if document.page_count != 1:
            raise ValueError("OCR fixture must contain exactly one page")
        embedded_text = document[0].get_text("text").strip()
        if embedded_text:
            raise ValueError("OCR fixture unexpectedly contains an embedded text layer")
    finally:
        document.close()

    def execute_pass(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        result = extract_pdf_text(
            "ocr-scanned-fixture-v2",
            OCR_PDF_PATH,
            output_dir=output_dir,
            overwrite=True,
            run_ocr=True,
            ocr_provider=TesseractOCRProvider(),
            expected_title="TTLAB OCR PIPELINE FIXTURE V2",
            max_pdf_bytes=5_242_880,
            max_pdf_pages=1,
        )
        manifest_path = output_dir / "ocr-scanned-fixture-v2.json"
        text_path = output_dir / "ocr-scanned-fixture-v2.txt"
        if not manifest_path.is_file() or not text_path.is_file():
            raise RuntimeError("full OCR extraction pipeline did not atomically publish both artifacts")
        persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if persisted_manifest != result:
            raise RuntimeError("persisted OCR manifest does not match the returned pipeline result")
        persisted_text_hash = sha256_file(text_path)
        if persisted_text_hash != result.get("text_artifact_sha256"):
            raise RuntimeError("persisted OCR text hash does not match its authoritative manifest")
        artifacts = {
            "manifest_readback_matches_returned_result": True,
            "text_sha256": persisted_text_hash,
            "text_bytes": text_path.stat().st_size,
        }
        return result, artifacts

    def sanitize_pass(result: dict[str, Any], artifacts: dict[str, Any]) -> dict[str, Any]:
        diagnostics = dict(result.get("diagnostics") or {})
        clean_diagnostics = redact_json_strings(diagnostics)
        if "ocr_configuration" in clean_diagnostics:
            clean_diagnostics["ocr_configuration"] = versionable_ocr_configuration(
                diagnostics.get("ocr_configuration")
            )
        pages = []
        for page in result.get("pages", []):
            clean_page = {
                key: redact_json_strings(value)
                for key, value in page.items()
                if key != "provenance"
            }
            if "ocr_configuration" in clean_page:
                clean_page["ocr_configuration"] = versionable_ocr_configuration(
                    page.get("ocr_configuration")
                )
            clean_page["provenance"] = {
                "input_fixture": relative(OCR_PDF_PATH),
                "page_number": (page.get("provenance") or {}).get("page_number"),
                "native_extractor": (page.get("provenance") or {}).get("native_extractor"),
                "ocr_provider": (page.get("provenance") or {}).get("ocr_provider"),
                "ocr_provider_version": (page.get("provenance") or {}).get("ocr_provider_version"),
                "ocr_configuration": versionable_ocr_configuration(
                    (page.get("provenance") or {}).get("ocr_configuration")
                ),
            }
            pages.append(clean_page)
        extraction_config = redact_json_strings(result.get("extraction_config") or {})
        if "ocr_configuration" in extraction_config:
            extraction_config["ocr_configuration"] = versionable_ocr_configuration(
                (result.get("extraction_config") or {}).get("ocr_configuration")
            )
        sanitized = {
            "paper_id": result.get("paper_id"),
            "input_fixture": relative(OCR_PDF_PATH),
            "page_count": result.get("page_count"),
            "pages": pages,
            "text_hash": result.get("text_hash"),
            "text_artifact_sha256": result.get("text_artifact_sha256"),
            "artifact_generation_id": result.get("artifact_generation_id"),
            "artifact_contract": result.get("artifact_contract"),
            "input_pdf_sha256": result.get("input_pdf_sha256"),
            "extraction_config": extraction_config,
            "extraction_status": result.get("extraction_status"),
            "warnings": redact_json_strings(result.get("warnings", [])),
            "diagnostics": clean_diagnostics,
            "sanitization": "temporary output paths removed; input path replaced by repository-relative fixture locator",
        }
        sanitized["persisted_artifacts"] = {
            **artifacts,
            "manifest_sanitized_sha256": sha256_bytes(canonical_json(sanitized).encode("utf-8")),
        }
        return sanitized

    with tempfile.TemporaryDirectory(prefix="ttlab-ocr-v2-") as temp_name:
        root = Path(temp_name)
        first_raw, first_artifacts = execute_pass(root / "pass-1")
        second_raw, second_artifacts = execute_pass(root / "pass-2")
    first = sanitize_pass(first_raw, first_artifacts)
    second = sanitize_pass(second_raw, second_artifacts)
    first_pages = first.get("pages", [])
    second_pages = second.get("pages", [])
    first_text = str(first_pages[0].get("text") or "") if first_pages else ""
    second_text = str(second_pages[0].get("text") or "") if second_pages else ""
    expected = normalize_text(gold["ground_truth_text"])
    observed = normalize_text(first_text)
    char_distance = levenshtein(expected, observed)
    expected_words = expected.split()
    observed_words = observed.split()
    word_distance = levenshtein(expected_words, observed_words)
    first_diagnostics = first.get("diagnostics", {})
    second_diagnostics = second.get("diagnostics", {})
    first_page = first_pages[0] if first_pages else {}
    second_page = second_pages[0] if second_pages else {}
    stable_first = {key: value for key, value in first.items() if key != "persisted_artifacts"}
    stable_second = {key: value for key, value in second.items() if key != "persisted_artifacts"}
    first_ocr_status = str(first_diagnostics.get("ocr_status") or "unknown")
    second_ocr_status = str(second_diagnostics.get("ocr_status") or "unknown")
    result = {
        "evaluation_id": "ocr-scanned-fixture-v2",
        "status": "completed"
        if first_ocr_status == second_ocr_status == "completed"
        else f"pass_1_{first_ocr_status}__pass_2_{second_ocr_status}",
        "fixture": relative(OCR_PDF_PATH),
        "fixture_sha256": sha256_file(OCR_PDF_PATH),
        "ground_truth_sha256": sha256_file(OCR_GOLD_PATH),
        "raster_only_assertion": {"embedded_text_character_count": 0, "passed": True},
        "provider": {
            "name": first_diagnostics.get("ocr_provider"),
            "version": first_diagnostics.get("ocr_provider_version"),
            "deterministic_configuration": versionable_ocr_configuration(
                deterministic_ocr_configuration()
            ),
            "pymupdf": package_version("PyMuPDF"),
            "pillow": package_version("Pillow"),
            "pytesseract": package_version("pytesseract"),
        },
        "parser_limits": {"max_pdf_bytes": 5_242_880, "max_pdf_pages": 1},
        "pipeline": "app.ingestion.pdf_parser.extract_pdf_text",
        "first_pass": first,
        "second_pass": second,
        "metrics": {
            "normalized_exact_match": expected == observed,
            "character_error_rate": round(char_distance / len(expected), 6) if expected else None,
            "word_error_rate": round(word_distance / len(expected_words), 6) if expected_words else None,
            "repeat_run_text_identical": first_text == second_text,
            "repeat_run_text_artifact_identical": first_artifacts["text_sha256"]
            == second_artifacts["text_sha256"],
            "repeat_run_configuration_identical": first.get("extraction_config")
            == second.get("extraction_config")
            and first_page.get("ocr_configuration") == second_page.get("ocr_configuration"),
            "repeat_run_sanitized_pipeline_result_identical": stable_first == stable_second,
            "content_type": first_diagnostics.get("content_type"),
            "possible_scanned_pdf": first_diagnostics.get("possible_scanned_pdf"),
            "ocr_status": first_ocr_status,
            "ocr_review_required": first_diagnostics.get("ocr_review_required"),
            "pdf_title_match_status": (first_diagnostics.get("pdf_title_match") or {}).get("status"),
            "page_extraction_method": first_page.get("extraction_method"),
            "page_content_class": first_page.get("content_class"),
        },
        "claim_boundary": "Synthetic raster-only pipeline exercise; not TTLAB corpus OCR accuracy, not a scanned-corpus prevalence estimate, and not human-reviewed OCR quality.",
    }
    write_json(OUTPUT_PATHS["ocr_results"], result)
    print(f"OCR fixture complete: status={result['status']}", flush=True)


def _macro_percent(value: Any) -> str:
    if value is None:
        return "not estimable"
    return f"{100 * float(value):.1f}\\%"


def _macro_signed_points(value: Any) -> str:
    if value is None:
        return "not estimable"
    return f"{100 * float(value):+.1f}~pp"


def _macro_decimal(value: Any) -> str:
    if value is None:
        return "not estimable"
    return f"{float(value):.3f}"


def _macro_escape(value: Any) -> str:
    return (
        str(value)
        .replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def _macro_interval(metric: dict[str, Any], formatter: Callable[[Any], str]) -> str:
    lower = metric.get("ci_lower")
    upper = metric.get("ci_upper")
    if lower is None or upper is None:
        return "not estimable"
    return f"[{formatter(lower)}, {formatter(upper)}]"


MANUSCRIPT_MACRO_NAMES = (
    "VTwoEvidenceTier",
    "VTwoRunStatus",
    "VTwoEvaluationId",
    "VTwoEvaluationSourceCommitPrefix",
    "VTwoProtocolShaPrefix",
    "VTwoFrozenDatasetShaPrefix",
    "VTwoLockedEnvironmentShaPrefix",
    "VTwoCorpusSnapshotId",
    "VTwoCorpusSnapshotShaPrefix",
    "VTwoTechnicalEligiblePapers",
    "VTwoTechnicalEligibleChunks",
    "VTwoKeywordIndexCompleteness",
    "VTwoKeywordConfigurationShaPrefix",
    "VTwoEvaluationScope",
    "VTwoPublicProjectionExercised",
    "VTwoExternalProviderInvoked",
    "VTwoQAProvider",
    "VTwoQAModel",
    "VTwoFinderProvider",
    "VTwoFinderModel",
    "VTwoTopicMethod",
    "VTwoOCRProvider",
    "VTwoOCRProviderVersion",
    "VTwoQATestCases",
    "VTwoQAAnswerabilityPrecision",
    "VTwoQAAnswerabilityPrecisionCi",
    "VTwoQAAnswerabilityRecall",
    "VTwoQAAnswerabilityRecallCi",
    "VTwoQAFalsePositiveRate",
    "VTwoQAFalsePositiveRateCi",
    "VTwoQAAbstentionRate",
    "VTwoQAAbstentionRateCi",
    "VTwoQACitationLocatorPrecision",
    "VTwoQACitationLocatorPrecisionCi",
    "VTwoQACitationCompleteness",
    "VTwoQACitationCompletenessCi",
    "VTwoQAAnswerPointCoverage",
    "VTwoQAAnswerPointCoverageCi",
    "VTwoFinderTestProfiles",
    "VTwoFinderEvidenceHitAtThree",
    "VTwoFinderEvidenceHitAtThreeCi",
    "VTwoFinderFullHitAtThree",
    "VTwoFinderFullHitAtThreeCi",
    "VTwoFinderHitAtThreeDelta",
    "VTwoFinderHitAtThreeDeltaCi",
    "VTwoFinderEvidenceMRR",
    "VTwoFinderEvidenceMRRCi",
    "VTwoFinderFullMRR",
    "VTwoFinderFullMRRCi",
    "VTwoFinderMRRDelta",
    "VTwoFinderMRRDeltaCi",
    "VTwoFinderTemplateConformance",
    "VTwoFinderFactSuggestionSeparation",
    "VTwoFinderUnknownTimeRetention",
    "VTwoFinderConstraintFidelity",
    "VTwoTopicTestCases",
    "VTwoTopicKnownPositiveRecall",
    "VTwoTopicKnownPositiveRecallCi",
    "VTwoTopicKnownPositiveCaseCoverage",
    "VTwoTopicKnownPositiveCaseCoverageCi",
    "VTwoTopicUnadjudicatedPredictionCount",
    "VTwoTopicUnadjudicatedPredictionShare",
    "VTwoOCRStatus",
    "VTwoOCRCharacterErrorRate",
    "VTwoOCRWordErrorRate",
    "VTwoOCRExactMatch",
    "VTwoOCRRepeatable",
)


def manuscript_macro_text(
    *,
    receipt: dict[str, Any] | None = None,
    corpus_identity: dict[str, Any] | None = None,
    keyword_index: dict[str, Any] | None = None,
) -> str:
    """Render deterministic LaTeX macros from completed v2 metrics and run identity.

    The canonical macro file deliberately excludes manifest and validation-
    attestation hashes: both are created after this output and including either
    would introduce a hash cycle. Downstream manuscript generators bind those
    files separately.
    """

    qa = json.loads(OUTPUT_PATHS["qa_metrics"].read_text(encoding="utf-8"))
    finder = json.loads(OUTPUT_PATHS["finder_metrics"].read_text(encoding="utf-8"))
    topics = json.loads(OUTPUT_PATHS["topic_metrics"].read_text(encoding="utf-8"))
    ocr = json.loads(OUTPUT_PATHS["ocr_results"].read_text(encoding="utf-8"))
    if any(item.get("status") != "completed" for item in (qa, finder, topics, ocr)):
        raise RuntimeError("v2 manuscript macros require completed component metrics")
    if receipt is None:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    if corpus_identity is None or keyword_index is None:
        manifest = json.loads(OUTPUT_PATHS["manifest"].read_text(encoding="utf-8"))
        corpus_identity = corpus_identity or manifest.get("technical_corpus_identity")
        keyword_index = keyword_index or manifest.get("temporary_keyword_index")
    if not isinstance(corpus_identity, dict) or not isinstance(keyword_index, dict):
        raise RuntimeError("v2 manuscript macros require corpus and keyword-index identities")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    qa_test = qa["by_split"]["test"]
    finder_test = finder["by_split"]["test"]
    topic_test = topics["by_split"]["test"]
    qa_metrics = qa_test["metrics"]
    finder_metrics = finder_test["metrics"]
    topic_known_positive = topic_test["known_positive_micro"]
    ocr_metrics = ocr["metrics"]
    qa_ci = qa["test_bootstrap_95_ci"]["metrics"]
    finder_ci = finder["test_bootstrap_95_ci"]["metrics"]
    topic_ci = topics["test_bootstrap_95_ci"]["metrics"]
    index_build = keyword_index.get("rebuild_result") or {}
    locked_identity = receipt.get("locked_validator_identity") or {}
    frozen_identity_sha = sha256_bytes(
        canonical_json(receipt.get("frozen_dataset_identity") or {}).encode("utf-8")
    )
    if receipt.get("public_projection_evaluated") is not False:
        raise RuntimeError("v2 manuscript macros cannot imply public-projection evaluation")
    macro_values = {
        "VTwoEvidenceTier": "AI-silver",
        "VTwoRunStatus": "completed metrics",
        "VTwoEvaluationId": "peer-review-remediation-v2",
        "VTwoEvaluationSourceCommitPrefix": _macro_escape(
            str(receipt["evaluation_source_commit"])[:12]
        ),
        "VTwoProtocolShaPrefix": sha256_file(PROTOCOL_PATH)[:12],
        "VTwoFrozenDatasetShaPrefix": frozen_identity_sha[:12],
        "VTwoLockedEnvironmentShaPrefix": str(locked_identity.get("lock_sha256") or "")[:12],
        "VTwoCorpusSnapshotId": _macro_escape(corpus_identity["snapshot_id"]),
        "VTwoCorpusSnapshotShaPrefix": str(corpus_identity["snapshot_hash"])[:12],
        "VTwoTechnicalEligiblePapers": str(corpus_identity["eligible_paper_count"]),
        "VTwoTechnicalEligibleChunks": str(corpus_identity["eligible_chunk_count"]),
        "VTwoKeywordIndexCompleteness": _macro_escape(index_build["completeness_status"]),
        "VTwoKeywordConfigurationShaPrefix": str(
            keyword_index.get("configuration_sha256") or ""
        )[:12],
        "VTwoEvaluationScope": "technical only",
        "VTwoPublicProjectionExercised": "no",
        "VTwoExternalProviderInvoked": "no",
        "VTwoQAProvider": _macro_escape(protocol["ask"]["provider"]),
        "VTwoQAModel": _macro_escape(protocol["ask"]["model_when_invoked"]),
        "VTwoFinderProvider": _macro_escape(protocol["finder"]["provider"]),
        "VTwoFinderModel": _macro_escape(protocol["finder"]["model"]),
        "VTwoTopicMethod": "controlled lexical rules",
        "VTwoOCRProvider": _macro_escape((ocr.get("provider") or {}).get("name") or "unknown"),
        "VTwoOCRProviderVersion": _macro_escape(
            (ocr.get("provider") or {}).get("version") or "unknown"
        ),
        "VTwoQATestCases": str(qa_test["case_count"]),
        "VTwoQAAnswerabilityPrecision": _macro_percent(qa_metrics["answerability_precision"]),
        "VTwoQAAnswerabilityPrecisionCi": _macro_interval(
            qa_ci["answerability_precision"], _macro_percent
        ),
        "VTwoQAAnswerabilityRecall": _macro_percent(qa_metrics["answerability_recall"]),
        "VTwoQAAnswerabilityRecallCi": _macro_interval(
            qa_ci["answerability_recall"], _macro_percent
        ),
        "VTwoQAFalsePositiveRate": _macro_percent(qa_metrics["false_positive_rate"]),
        "VTwoQAFalsePositiveRateCi": _macro_interval(
            qa_ci["false_positive_rate"], _macro_percent
        ),
        "VTwoQAAbstentionRate": _macro_percent(qa_metrics["abstention_rate"]),
        "VTwoQAAbstentionRateCi": _macro_interval(
            qa_ci["abstention_rate"], _macro_percent
        ),
        "VTwoQACitationLocatorPrecision": _macro_percent(
            qa_metrics["exact_gold_locator_citation_precision"]
        ),
        "VTwoQACitationLocatorPrecisionCi": _macro_interval(
            qa_ci["exact_gold_locator_citation_precision"], _macro_percent
        ),
        "VTwoQACitationCompleteness": _macro_percent(qa_metrics["citation_completeness"]),
        "VTwoQACitationCompletenessCi": _macro_interval(
            qa_ci["citation_completeness"], _macro_percent
        ),
        "VTwoQAAnswerPointCoverage": _macro_percent(qa_metrics["answer_point_coverage"]),
        "VTwoQAAnswerPointCoverageCi": _macro_interval(
            qa_ci["answer_point_coverage"], _macro_percent
        ),
        "VTwoFinderTestProfiles": str(finder_test["profile_count"]),
        "VTwoFinderEvidenceHitAtThree": _macro_percent(finder_metrics["evidence_only_hit_at_3"]),
        "VTwoFinderEvidenceHitAtThreeCi": _macro_interval(
            finder_ci["evidence_only_hit_at_3"], _macro_percent
        ),
        "VTwoFinderFullHitAtThree": _macro_percent(finder_metrics["full_finder_hit_at_3"]),
        "VTwoFinderFullHitAtThreeCi": _macro_interval(
            finder_ci["full_finder_hit_at_3"], _macro_percent
        ),
        "VTwoFinderHitAtThreeDelta": _macro_signed_points(finder_metrics["paired_hit_at_3_delta"]),
        "VTwoFinderHitAtThreeDeltaCi": _macro_interval(
            finder_ci["paired_hit_at_3_delta"], _macro_signed_points
        ),
        "VTwoFinderEvidenceMRR": _macro_decimal(finder_metrics["evidence_only_mrr"]),
        "VTwoFinderEvidenceMRRCi": _macro_interval(
            finder_ci["evidence_only_mrr"], _macro_decimal
        ),
        "VTwoFinderFullMRR": _macro_decimal(finder_metrics["full_finder_mrr"]),
        "VTwoFinderFullMRRCi": _macro_interval(finder_ci["full_finder_mrr"], _macro_decimal),
        "VTwoFinderMRRDelta": _macro_decimal(finder_metrics["paired_mrr_delta"]),
        "VTwoFinderMRRDeltaCi": _macro_interval(
            finder_ci["paired_mrr_delta"], _macro_decimal
        ),
        "VTwoFinderTemplateConformance": _macro_percent(
            finder_metrics["candidate_specific_template_conformance_rate"]
        ),
        "VTwoFinderFactSuggestionSeparation": _macro_percent(
            finder_metrics["source_fact_suggestion_separation_rate"]
        ),
        "VTwoFinderUnknownTimeRetention": _macro_percent(
            finder_metrics["unknown_implementation_time_retention_rate"]
        ),
        "VTwoFinderConstraintFidelity": _macro_percent(
            finder_metrics["full_profile_constraint_contract_fidelity_rate"]
        ),
        "VTwoTopicTestCases": str(topic_test["case_count"]),
        "VTwoTopicKnownPositiveRecall": _macro_percent(topic_known_positive["recall"]),
        "VTwoTopicKnownPositiveRecallCi": _macro_interval(
            topic_ci["known_positive_micro_recall"], _macro_percent
        ),
        "VTwoTopicKnownPositiveCaseCoverage": _macro_percent(
            topic_test["known_positive_case_coverage_rate"]
        ),
        "VTwoTopicKnownPositiveCaseCoverageCi": _macro_interval(
            topic_ci["known_positive_case_coverage_rate"], _macro_percent
        ),
        "VTwoTopicUnadjudicatedPredictionCount": str(
            topic_test["unadjudicated_predictions"]["count"]
        ),
        "VTwoTopicUnadjudicatedPredictionShare": _macro_percent(
            topic_test["unadjudicated_predictions"]["share"]
        ),
        "VTwoOCRStatus": str(ocr["status"]).replace("_", "\\_"),
        "VTwoOCRCharacterErrorRate": _macro_percent(ocr_metrics["character_error_rate"]),
        "VTwoOCRWordErrorRate": _macro_percent(ocr_metrics["word_error_rate"]),
        "VTwoOCRExactMatch": "yes" if ocr_metrics["normalized_exact_match"] else "no",
        "VTwoOCRRepeatable": "yes"
        if all(
            ocr_metrics[key]
            for key in (
                "repeat_run_text_identical",
                "repeat_run_text_artifact_identical",
                "repeat_run_configuration_identical",
                "repeat_run_sanitized_pipeline_result_identical",
            )
        )
        else "no",
    }
    if tuple(macro_values) != MANUSCRIPT_MACRO_NAMES:
        raise RuntimeError("v2 manuscript macro contract/order drift")
    lines = [
        "% Generated deterministically from peer-review-remediation v2 artifacts.",
        "% AI-silver technical-corpus evidence; not human validation or entailment evidence.",
    ]
    lines.extend(f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macro_values.items())
    return "\n".join(lines) + "\n"


def write_manuscript_macros(
    receipt: dict[str, Any],
    corpus_identity: dict[str, Any],
    keyword_index: dict[str, Any],
) -> None:
    write_text(
        OUTPUT_PATHS["manuscript_macros"],
        manuscript_macro_text(
            receipt=receipt,
            corpus_identity=corpus_identity,
            keyword_index=keyword_index,
        ),
    )
    print(f"Manuscript macros written to {relative(OUTPUT_PATHS['manuscript_macros'])}", flush=True)


def validate_runtime_provenance_outputs(
    corpus_identity: dict[str, Any],
    keyword_index: dict[str, Any],
) -> dict[str, Any]:
    required = {
        "code_identity",
        "corpus_identity",
        "source_identity",
        "retrieval_identity",
        "generation_identity",
    }
    expected_corpus = {
        key: corpus_identity[key]
        for key in ("snapshot_id", "snapshot_hash", "eligible_chunk_count", "eligible_paper_count")
    }
    records: list[tuple[str, dict[str, Any], dict[str, str], str, str]] = []
    for row in read_jsonl(OUTPUT_PATHS["qa_raw"]):
        hashes = {
            str(item["chunk_id"]): str(item.get("effective_source_sha256") or "")
            for item in row.get("retrieved_chunks", [])
        }
        records.append(
            (
                f"ask:{row['case_id']}",
                row.get("runtime_provenance") or {},
                hashes,
                str(row.get("provider") or ""),
                str(row.get("model") or ""),
            )
        )
    for row in read_jsonl(OUTPUT_PATHS["finder_raw"]):
        hashes = {
            str(item["chunk_id"]): str(item.get("effective_source_sha256") or "")
            for item in (row.get("paired_retrieval") or {}).get("result_locators", [])
        }
        full = row.get("full_finder") or {}
        records.append(
            (
                f"finder:{row['profile_id']}",
                full.get("runtime_provenance") or {},
                hashes,
                str(full.get("provider") or ""),
                str(full.get("model") or ""),
            )
        )
    code_identities: list[dict[str, Any]] = []
    expected_completeness = keyword_index["rebuild_result"]["completeness_status"]
    for record_id, provenance, available_hashes, provider, model in records:
        if not required.issubset(provenance):
            raise RuntimeError(f"{record_id}: incomplete runtime provenance")
        if provenance.get("corpus_identity") != expected_corpus:
            raise RuntimeError(f"{record_id}: runtime corpus identity drift")
        source_identity = provenance.get("source_identity") or {}
        chunk_ids = list(source_identity.get("chunk_ids") or [])
        if chunk_ids != sorted(set(chunk_ids)):
            raise RuntimeError(f"{record_id}: runtime source chunk IDs are not canonical")
        if chunk_ids != sorted(available_hashes):
            raise RuntimeError(
                f"{record_id}: declared runtime source IDs do not exactly equal serialized retrieval IDs"
            )
        source_hashes = {chunk_id: available_hashes.get(chunk_id, "") for chunk_id in chunk_ids}
        if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in source_hashes.values()):
            raise RuntimeError(f"{record_id}: missing effective source identity")
        expected_source_descriptor = sha256_bytes(canonical_json(source_hashes).encode("utf-8"))
        if source_identity.get("chunk_descriptor_sha256") != expected_source_descriptor:
            raise RuntimeError(f"{record_id}: source descriptor hash mismatch")
        retrieval = provenance.get("retrieval_identity") or {}
        if retrieval.get("mode") != "keyword" or retrieval.get("scope") != "technical":
            raise RuntimeError(f"{record_id}: runtime retrieval identity is not keyword/technical")
        keyword_reports = [item for item in retrieval.get("indexes", []) if item.get("kind") == "keyword"]
        if len(keyword_reports) != 1:
            raise RuntimeError(f"{record_id}: runtime keyword-index identity is missing or ambiguous")
        keyword_report = keyword_reports[0]
        if expected_completeness == "complete":
            if keyword_report.get("status") != "ready" or keyword_report.get("completeness_status") != "complete":
                raise RuntimeError(f"{record_id}: runtime keyword-index identity is not complete")
            if keyword_report.get("corpus_snapshot_hash") != corpus_identity["snapshot_hash"]:
                raise RuntimeError(f"{record_id}: runtime keyword-index corpus identity drift")
        generation = provenance.get("generation_identity") or {}
        if generation.get("provider") != provider or generation.get("model") != model:
            raise RuntimeError(f"{record_id}: generation identity does not match the raw response")
        if record_id.startswith("ask:"):
            if provider not in {"offline_extractive", "not_invoked"}:
                raise RuntimeError(f"{record_id}: unpinned Ask provider was invoked")
            if provider == "offline_extractive" and model != "sentence-overlap-v1":
                raise RuntimeError(f"{record_id}: unpinned Ask model was invoked")
        elif (provider, model) != ("offline_deterministic", "template-recommender-v1"):
            raise RuntimeError(f"{record_id}: unpinned Finder provider/model was invoked")
        if provider == "not_invoked":
            if record_id.startswith("finder:") or generation.get("immutable_model_identity") is not False:
                raise RuntimeError(f"{record_id}: invalid not-invoked model identity")
        elif generation.get("immutable_model_identity") is not True:
            raise RuntimeError(f"{record_id}: generation model identity is mutable")
        code_identity = provenance.get("code_identity") or {}
        if code_identity.get("scope") != "backend/app" or code_identity.get("status") != "clean_commit":
            raise RuntimeError(f"{record_id}: backend runtime must resolve to a clean commit")
        code_identities.append(code_identity)
    if not records:
        raise RuntimeError("no Ask/Finder runtime provenance records were produced")
    if any(identity != code_identities[0] for identity in code_identities[1:]):
        raise RuntimeError("backend code identity changed during evaluation")
    return {
        "status": "verified",
        "record_count": len(records),
        "ask_record_count": sum(record_id.startswith("ask:") for record_id, *_ in records),
        "finder_record_count": sum(record_id.startswith("finder:") for record_id, *_ in records),
        "required_fields": sorted(required),
        "code_identity": code_identities[0],
        "corpus_identity": expected_corpus,
        "source_descriptors_verified": True,
        "retrieval_scope": "technical",
        "public_projection_exercised": False,
    }


def build_manifest(
    receipt: dict[str, Any],
    temp_db: Path,
    keyword_index: dict[str, Any],
    corpus_identity: dict[str, Any],
) -> None:
    if require_clean_committed_evaluation_sources() != receipt.get("evaluation_source_commit"):
        raise RuntimeError("evaluation source commit changed during execution")
    changed_after_execution = [
        raw_path
        for raw_path, metadata in receipt["files"].items()
        if not (ROOT / raw_path).is_file()
        or sha256_file(ROOT / raw_path) != metadata["sha256"]
    ]
    if changed_after_execution:
        raise RuntimeError(f"frozen inputs changed during evaluation: {changed_after_execution}")
    if corpus_snapshot() != receipt["corpus_snapshot"]:
        raise RuntimeError("logical paper/chunk corpus changed during evaluation")
    if generation_artifact_inventory() != receipt.get("generation_artifact_inventory"):
        raise RuntimeError("PDF/extraction/chunk artifact inventory changed during evaluation")
    runtime_provenance = validate_runtime_provenance_outputs(corpus_identity, keyword_index)
    if (runtime_provenance.get("code_identity") or {}).get("git_commit") != receipt.get(
        "evaluation_source_commit"
    ):
        raise RuntimeError("runtime backend commit differs from the frozen evaluation source commit")
    restricted_inventory = restricted_output_inventory()
    missing_outputs = [
        key for key, path in OUTPUT_PATHS.items() if key != "manifest" and not path.is_file()
    ]
    if missing_outputs:
        raise RuntimeError(f"required versionable outputs were not produced: {missing_outputs}")
    output_files = {
        relative(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for key, path in OUTPUT_PATHS.items()
        if key != "manifest" and path.is_file()
    }
    manifest = {
        "evaluation_id": "peer-review-remediation-v2",
        "status": "completed",
        "completed_at": utc_now(),
        "freeze_receipt": relative(RECEIPT_PATH),
        "freeze_receipt_sha256": sha256_file(RECEIPT_PATH),
        "frozen_at": receipt["frozen_at"],
        "evaluation_source_commit": receipt["evaluation_source_commit"],
        "frozen_dataset_identity": receipt["frozen_dataset_identity"],
        "locked_validator_identity": receipt["locked_validator_identity"],
        "tracked_database_mutated": False,
        "temporary_database": {
            "path_retained": False,
            "source_sha256": sha256_file(DB_PATH),
            "source_expected_sha256": receipt["files"][relative(DB_PATH)]["sha256"],
            "source_unchanged_during_execution": True,
            "temporary_integrity_check": sqlite_integrity_check(temp_db),
        },
        "post_execution_frozen_inputs_unchanged": True,
        "reviewer": REVIEWER,
        "technical_scope_only": True,
        "technical_selection_predicate": TECHNICAL_SELECTION_PREDICATE,
        "technical_corpus_identity": corpus_identity,
        "temporary_keyword_index": keyword_index,
        "provider_environment_overrides": EVALUATION_ENVIRONMENT,
        "runtime_provenance_validation": runtime_provenance,
        "public_validation_claimed": False,
        "public_projection_exercised": False,
        "public_selection_predicate_recorded_not_tested": PUBLIC_SELECTION_PREDICATE,
        "entailment_claimed": False,
        "human_validation_claimed": False,
        "v1_artifacts_overwritten": False,
        "outputs": output_files,
        "restricted_raw_outputs": restricted_inventory,
        "release_contains_rights_sensitive_raw_text": False,
        "claim_boundary": "This package is AI-silver technical-corpus evaluation evidence. It does not establish public eligibility, human usefulness, semantic entailment, novelty, practical feasibility, or corpus OCR accuracy.",
    }
    write_json(OUTPUT_PATHS["manifest"], manifest)


def sqlite_integrity_check(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def execute_evaluation() -> None:
    static_validation = invoke_locked_validator("--static-only")
    receipt = verify_frozen_inputs()
    if static_validation["identity"] != receipt.get("locked_validator_identity"):
        raise RuntimeError("evaluate did not use the validator/environment frozen during prepare")
    sys.path.insert(0, str(ROOT / "backend"))
    with tempfile.TemporaryDirectory(prefix="ttlab-eval-v2-") as temp_name:
        temp_dir = Path(temp_name)
        temp_db = initialize_temporary_database(temp_dir)
        from app.db import create_db_and_tables, engine
        from app.ingestion.generation_reconciler import reconcile_generation_links
        from app.models import Chunk, Paper
        from sqlmodel import Session

        create_db_and_tables()
        with Session(engine) as session:
            reconciliation = reconcile_generation_links(
                session,
                project_root=ROOT,
                extraction_dir=ROOT / "data" / "extracted_text",
                chunks_dir=ROOT / "data" / "chunks",
                pdf_dir=ROOT / "data" / "pdfs",
            )
            keyword_index, corpus_identity = prepare_temporary_keyword_index(
                session,
                generation_reconciliation=reconciliation,
            )
            run_qa(session, Chunk)
            run_finder(session, Chunk)
            run_topics(session, Chunk, Paper)
        run_ocr()
        write_manuscript_macros(receipt, corpus_identity, keyword_index)
        build_manifest(receipt, temp_db, keyword_index, corpus_identity)
    completed_validation = invoke_locked_validator("--write-attestation")
    if completed_validation["identity"] != receipt.get("locked_validator_identity"):
        raise RuntimeError("completed-package validation used a different locked environment")
    print(f"Evaluation manifest written to {relative(OUTPUT_PATHS['manifest'])}", flush=True)
    print(
        f"Validation attestation written to {relative(VALIDATION_ATTESTATION_PATH)}",
        flush=True,
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subparsers = value.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "prepare",
        help="validate in the locked environment, freeze all prospective inputs, and generate the OCR fixture",
    )
    subparsers.add_parser("evaluate", help="verify the freeze and execute the fixed suite once")
    normalized = subparsers.add_parser(
        "normalized-hash",
        help="hash an artifact after removing timestamp fields only",
    )
    normalized.add_argument("path", type=Path)
    return value


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        freeze_inputs()
    elif args.command == "evaluate":
        execute_evaluation()
    elif args.command == "normalized-hash":
        print(normalized_artifact_sha256(args.path.resolve()))


if __name__ == "__main__":
    main()
