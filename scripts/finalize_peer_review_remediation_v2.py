#!/usr/bin/env python3
"""Finalize the one known remediation-v2 post-evaluation packaging failure.

This is deliberately not a general repair tool.  It may run only after the
single prospective ``evaluate`` invocation produced every pre-manifest output
and then failed while checking the known runtime-provenance representation
mismatch.  It preserves every file it changes outside the detached source
tree, performs the two representation-only normalizations, builds the manifest,
and asks the frozen validator to write the strict restricted-raw attestation.

It never executes or re-scores an evaluation case.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


EXPECTED_QA_ROWS = 18
EXPECTED_FINDER_ROWS = 10
EXPECTED_TOPIC_ROWS = 12
CORPUS_IDENTITY_FIELDS_WITH_REDUNDANT_SCOPE = {
    "scope",
    "snapshot_id",
    "snapshot_hash",
    "eligible_chunk_count",
    "eligible_paper_count",
}
KNOWN_FAILURE_COMPLETION_MARKERS = (
    "Ask evaluation complete: 18 frozen cases",
    "Finder evaluation complete: 10 frozen profiles",
    "Topic evaluation complete: 12 source cases",
    "OCR fixture complete: status=completed",
    "Manuscript macros written to artifacts/peer_review_remediation/v2/manuscript_macros_v2.tex",
)
KNOWN_FAILURE_FINAL_LINE = "RuntimeError: ask:qa-v2-a01: runtime corpus identity drift"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path.name}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{path.name}:{line_number}: expected an object")
        rows.append(value)
    return rows


def jsonl_payload(rows: list[dict[str, Any]]) -> bytes:
    return ("".join(f"{canonical_json(row)}\n" for row in rows)).encode("utf-8")


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_json_atomic(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    write_bytes_atomic(path, payload)


def require_regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")


def validate_known_failure_log(text: str) -> None:
    if text.count("Traceback (most recent call last):") != 1:
        raise RuntimeError("evaluation log does not contain exactly one traceback")
    for marker in KNOWN_FAILURE_COMPLETION_MARKERS:
        if marker not in text:
            raise RuntimeError(f"evaluation log lacks the completed-stage marker: {marker}")
    for marker in (
        "execute_evaluation",
        "build_manifest(receipt, temp_db, keyword_index, corpus_identity)",
        "runtime_provenance = validate_runtime_provenance_outputs(corpus_identity, keyword_index)",
        "raise RuntimeError(f\"{record_id}: runtime corpus identity drift\")",
    ):
        if marker not in text:
            raise RuntimeError(f"evaluation log lacks the known packaging-failure frame: {marker}")
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not nonempty_lines or nonempty_lines[-1] != KNOWN_FAILURE_FINAL_LINE:
        raise RuntimeError("evaluation log did not end with the exact known provenance mismatch")


def provenance_for(row: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "qa":
        provenance = row.get("runtime_provenance") or (row.get("response") or {}).get(
            "runtime_provenance"
        )
    elif kind == "finder":
        provenance = (row.get("full_finder") or {}).get("runtime_provenance")
    else:
        raise RuntimeError(f"unsupported recovery record kind: {kind}")
    if not isinstance(provenance, dict):
        raise RuntimeError(f"{kind} row lacks runtime provenance")
    return provenance


def record_id(row: dict[str, Any], kind: str) -> str:
    key = "case_id" if kind == "qa" else "profile_id"
    value = str(row.get(key) or "")
    if not value:
        raise RuntimeError(f"{kind} row lacks {key}")
    return value


def source_hashes_from_locators(locators: Any, label: str) -> dict[str, str]:
    if not isinstance(locators, list) or not locators:
        raise RuntimeError(f"{label}: serialized retrieval locator set is empty")
    hashes: dict[str, str] = {}
    for item in locators:
        if not isinstance(item, dict):
            raise RuntimeError(f"{label}: retrieval locator is not an object")
        chunk_id = str(item.get("chunk_id") or "")
        source_hash = str(item.get("effective_source_sha256") or "")
        if not chunk_id or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise RuntimeError(f"{label}: retrieval locator lacks an effective source identity")
        if chunk_id in hashes:
            raise RuntimeError(f"{label}: duplicate serialized retrieval chunk ID: {chunk_id}")
        hashes[chunk_id] = source_hash
    return hashes


def qa_source_hashes(row: dict[str, Any], label: str) -> dict[str, str]:
    locators = row.get("retrieved_chunks")
    if locators is None:
        locators = (row.get("response") or {}).get("retrieved_chunks")
    return source_hashes_from_locators(locators, label)


def validate_source_identity(
    provenance: dict[str, Any],
    available_hashes: dict[str, str],
    label: str,
    *,
    allow_subset: bool,
) -> tuple[list[str], list[str]]:
    identity = provenance.get("source_identity")
    if not isinstance(identity, dict) or set(identity) != {
        "chunk_ids",
        "chunk_descriptor_sha256",
    }:
        raise RuntimeError(f"{label}: unexpected runtime source-identity shape")
    chunk_ids = identity.get("chunk_ids")
    if not isinstance(chunk_ids, list) or chunk_ids != sorted(set(chunk_ids)):
        raise RuntimeError(f"{label}: source chunk IDs are not sorted and unique")
    declared = [str(value) for value in chunk_ids]
    available = sorted(available_hashes)
    if allow_subset:
        if not declared or not set(declared).issubset(available_hashes):
            raise RuntimeError(
                f"{label}: cited Finder source IDs are not a non-empty retrieval subset"
            )
    elif declared != available:
        raise RuntimeError(f"{label}: QA source IDs do not exactly equal serialized retrieval IDs")
    declared_hashes = {chunk_id: available_hashes[chunk_id] for chunk_id in declared}
    expected_descriptor = sha256_bytes(canonical_json(declared_hashes).encode("utf-8"))
    if identity.get("chunk_descriptor_sha256") != expected_descriptor:
        raise RuntimeError(f"{label}: existing source descriptor is not valid for its declared IDs")
    return declared, available


def normalize_rows(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    expected_rows: int,
    expected_source_hashes: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    if len(rows) != expected_rows:
        raise RuntimeError(f"{kind}: expected {expected_rows} rows, found {len(rows)}")
    normalized = copy.deepcopy(rows)
    identities: dict[str, dict[str, Any]] = {}
    finder_source_mismatches = 0
    corpus_identity: dict[str, Any] | None = None
    for row in normalized:
        identity = record_id(row, kind)
        if identity in identities:
            raise RuntimeError(f"{kind}: duplicate record ID: {identity}")
        provenance = provenance_for(row, kind)
        corpus = provenance.get("corpus_identity")
        if (
            not isinstance(corpus, dict)
            or set(corpus) != CORPUS_IDENTITY_FIELDS_WITH_REDUNDANT_SCOPE
        ):
            raise RuntimeError(
                f"{kind}:{identity}: corpus identity is not the exact known redundant shape"
            )
        if corpus.get("scope") != "technical":
            raise RuntimeError(f"{kind}:{identity}: redundant corpus scope is not technical")
        if corpus_identity is None:
            corpus_identity = dict(corpus)
        elif corpus != corpus_identity:
            raise RuntimeError(f"{kind}:{identity}: runtime corpus identity varies between records")
        del corpus["scope"]

        if kind == "qa":
            available_hashes = (expected_source_hashes or {}).get(identity) or qa_source_hashes(
                row, f"{kind}:{identity}"
            )
            declared, available = validate_source_identity(
                provenance,
                available_hashes,
                f"{kind}:{identity}",
                allow_subset=False,
            )
        else:
            available_hashes = (expected_source_hashes or {}).get(identity) or {}
            declared, available = validate_source_identity(
                provenance,
                available_hashes,
                f"{kind}:{identity}",
                allow_subset=True,
            )
            if declared != available:
                finder_source_mismatches += 1
            provenance["source_identity"] = {
                "chunk_ids": available,
                "chunk_descriptor_sha256": sha256_bytes(
                    canonical_json(available_hashes).encode("utf-8")
                ),
            }
        identities[identity] = {
            "corpus_identity": corpus_identity,
            "declared_source_ids_before": declared,
            "complete_source_ids": available,
        }
    return normalized, {
        "rows": len(rows),
        "records_with_redundant_scope_removed": len(rows),
        "finder_source_identity_records_corrected": finder_source_mismatches,
    }, identities


def prepare_normalized_payloads(
    qa_public_path: Path,
    qa_restricted_path: Path,
    finder_public_path: Path,
    finder_restricted_path: Path,
) -> tuple[dict[Path, bytes], list[dict[str, Any]]]:
    qa_public = read_jsonl(qa_public_path)
    qa_restricted = read_jsonl(qa_restricted_path)
    finder_public = read_jsonl(finder_public_path)
    finder_restricted = read_jsonl(finder_restricted_path)

    finder_hashes: dict[str, dict[str, str]] = {}
    for row in finder_public:
        identity = record_id(row, "finder")
        if identity in finder_hashes:
            raise RuntimeError(f"finder: duplicate public profile ID: {identity}")
        finder_hashes[identity] = source_hashes_from_locators(
            (row.get("paired_retrieval") or {}).get("result_locators"),
            f"finder:{identity}",
        )
    qa_hashes: dict[str, dict[str, str]] = {}
    for row in qa_public:
        identity = record_id(row, "qa")
        if identity in qa_hashes:
            raise RuntimeError(f"qa: duplicate public case ID: {identity}")
        qa_hashes[identity] = qa_source_hashes(row, f"qa:{identity}")

    specifications = (
        (qa_public_path, qa_public, "qa", EXPECTED_QA_ROWS, qa_hashes),
        (qa_restricted_path, qa_restricted, "qa", EXPECTED_QA_ROWS, qa_hashes),
        (finder_public_path, finder_public, "finder", EXPECTED_FINDER_ROWS, finder_hashes),
        (
            finder_restricted_path,
            finder_restricted,
            "finder",
            EXPECTED_FINDER_ROWS,
            finder_hashes,
        ),
    )
    payloads: dict[Path, bytes] = {}
    reports: list[dict[str, Any]] = []
    identities_by_file: dict[Path, dict[str, dict[str, Any]]] = {}
    corpus_identities: list[dict[str, Any]] = []
    for path, rows, kind, expected_rows, expected_hashes in specifications:
        normalized, report, identities = normalize_rows(
            rows,
            kind=kind,
            expected_rows=expected_rows,
            expected_source_hashes=expected_hashes,
        )
        payload = jsonl_payload(normalized)
        payloads[path] = payload
        identities_by_file[path] = identities
        corpus_identities.append(next(iter(identities.values()))["corpus_identity"])
        reports.append(
            {
                "path": path.name,
                **report,
                "original_sha256": sha256_file(path),
                "normalized_sha256": sha256_bytes(payload),
            }
        )

    if any(identity != corpus_identities[0] for identity in corpus_identities[1:]):
        raise RuntimeError("QA and Finder outputs do not share one exact runtime corpus identity")
    for public_path, restricted_path in (
        (qa_public_path, qa_restricted_path),
        (finder_public_path, finder_restricted_path),
    ):
        public = identities_by_file[public_path]
        restricted = identities_by_file[restricted_path]
        if set(public) != set(restricted):
            raise RuntimeError(f"{public_path.name}: public/restricted record IDs differ")
        for identity in public:
            if public[identity] != restricted[identity]:
                raise RuntimeError(
                    f"{public_path.name}:{identity}: public/restricted provenance identities differ"
                )
    finder_reports = [report for report in reports if report["path"].startswith("finder_")]
    if not finder_reports or any(
        int(report["finder_source_identity_records_corrected"]) <= 0
        for report in finder_reports
    ):
        raise RuntimeError(
            "Finder outputs do not contain the exact known incomplete-source mismatch"
        )
    return payloads, reports


def run_git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def finalizer_identity(root: Path) -> dict[str, Any]:
    relative_path = Path("scripts/finalize_peer_review_remediation_v2.py")
    local_path = root / relative_path
    require_regular_file(local_path, "recovery script")
    head = run_git(root, "rev-parse", "HEAD").decode().strip()
    tracked_payload = run_git(root, "show", f"{head}:{relative_path.as_posix()}")
    local_payload = local_path.read_bytes()
    if tracked_payload != local_payload:
        raise RuntimeError("recovery script differs from the committed source identity")
    return {
        "path": relative_path.as_posix(),
        "sha256": sha256_bytes(local_payload),
        "git_commit": head,
        "status": "clean_committed_file",
    }


def load_runner(root: Path) -> ModuleType:
    path = root / "data" / "evaluation" / "run_peer_review_remediation_v2.py"
    require_regular_file(path, "v2 runner")
    sys.path.insert(0, str(root / "data" / "evaluation"))
    sys.path.insert(0, str(root / "backend"))
    spec = importlib.util.spec_from_file_location("ttlab_v2_recovery_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen remediation-v2 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_directory_inventory(directory: Path, expected: set[str], label: str) -> None:
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError(f"{label} directory is absent or unsafe: {directory}")
    entries = {path.name for path in directory.iterdir()}
    if entries != expected:
        missing = sorted(expected - entries)
        unexpected = sorted(entries - expected)
        raise RuntimeError(f"{label} inventory drift; missing={missing}, unexpected={unexpected}")
    for name in expected:
        require_regular_file(directory / name, label)


def archive_originals(
    archive_dir: Path,
    log_path: Path,
    changed_paths: tuple[Path, ...],
    pre_manifest_paths: tuple[Path, ...],
    restricted_paths: tuple[Path, ...],
) -> dict[str, Any]:
    if archive_dir.exists():
        raise RuntimeError(
            f"recovery archive already exists; refusing a second finalization: {archive_dir}"
        )
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = archive_dir.with_name(f".{archive_dir.name}.tmp-{os.getpid()}")
    if staging.exists():
        raise RuntimeError(f"recovery archive staging path already exists: {staging}")
    try:
        original_dir = staging / "original-runtime-raw"
        original_dir.mkdir(parents=True)
        for path in changed_paths:
            shutil.copy2(path, original_dir / path.name)
        shutil.copy2(log_path, staging / log_path.name)
        inventory = {
            "evaluation_log": {
                "filename": log_path.name,
                "sha256": sha256_file(log_path),
                "bytes": log_path.stat().st_size,
            },
            "changed_originals": {
                path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in changed_paths
            },
            "pre_manifest_outputs": {
                path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in pre_manifest_paths
            },
            "restricted_outputs": {
                path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in restricted_paths
            },
        }
        write_json_atomic(staging / "original_inventory.json", inventory)
        os.replace(staging, archive_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return inventory


def finalize(root: Path, work: Path) -> dict[str, Any]:
    root = root.resolve()
    work = work.resolve()
    if root != work / "source":
        raise RuntimeError(
            "recovery is restricted to the detached <work-dir>/source reproduction tree"
        )
    log_path = work / "logs" / "remediation-v2-evaluate.log"
    archive_dir = work / "artifacts" / "v2-manifest-recovery"
    runtime_tmp = work / "runtime-tmp"
    if archive_dir == root or archive_dir.is_relative_to(root):
        raise RuntimeError("recovery archive must remain outside the detached source tree")
    require_regular_file(log_path, "preserved evaluate log")
    if not runtime_tmp.is_dir() or runtime_tmp.is_symlink():
        raise RuntimeError("reproduction runtime-tmp directory is absent or unsafe")
    validate_known_failure_log(log_path.read_text(encoding="utf-8"))

    artifact_dir = root / "artifacts" / "peer_review_remediation" / "v2"
    restricted_dir = work / "restricted" / "peer_review_remediation" / "v2"
    os.environ["PYTHONPATH"] = str(root / "backend")
    os.environ["TTLAB_V2_ARTIFACT_DIR"] = str(artifact_dir)
    os.environ["TTLAB_V2_RESTRICTED_DIR"] = str(restricted_dir)
    for name in ("TMPDIR", "TEMP", "TMP"):
        os.environ[name] = str(runtime_tmp)
    for name in (
        "TTLAB_DATABASE_URL",
        "TTLAB_ALLOWED_LLM_PROVIDERS",
        "TTLAB_DEFAULT_LLM_PROVIDER",
    ):
        os.environ.pop(name, None)
    runner = load_runner(root)
    if Path(runner.ROOT).resolve() != root:
        raise RuntimeError("loaded v2 runner resolved a different repository root")
    if (
        Path(runner.OUT_DIR).resolve() != artifact_dir
        or Path(runner.RESTRICTED_OUT_DIR).resolve() != restricted_dir
    ):
        raise RuntimeError("v2 runner output paths differ from the isolated reproduction contract")
    if runner.OUTPUT_PATHS["manifest"].exists() or runner.VALIDATION_ATTESTATION_PATH.exists():
        raise RuntimeError(
            "manifest or attestation already exists; refusing duplicate finalization"
        )

    pre_manifest_paths = (
        Path(runner.RECEIPT_PATH),
        *(Path(path) for key, path in runner.OUTPUT_PATHS.items() if key != "manifest"),
    )
    restricted_paths = tuple(Path(path) for path in runner.RESTRICTED_OUTPUT_PATHS.values())
    if len(pre_manifest_paths) != 15 or len(restricted_paths) != 3:
        raise RuntimeError("frozen runner no longer exposes the exact 15+3 recovery inventory")
    exact_directory_inventory(
        artifact_dir,
        {path.name for path in pre_manifest_paths},
        "versionable pre-manifest",
    )
    exact_directory_inventory(
        restricted_dir,
        {path.name for path in restricted_paths},
        "restricted raw",
    )
    if len(read_jsonl(Path(runner.OUTPUT_PATHS["topic_predictions"]))) != EXPECTED_TOPIC_ROWS:
        raise RuntimeError("topic output row count differs from the completed known run")
    if (
        len(read_jsonl(Path(runner.RESTRICTED_OUTPUT_PATHS["topic_full_raw"])))
        != EXPECTED_TOPIC_ROWS
    ):
        raise RuntimeError("restricted topic output row count differs from the completed known run")

    identity = finalizer_identity(root)
    receipt = json.loads(Path(runner.RECEIPT_PATH).read_text(encoding="utf-8"))
    if receipt.get("evaluation_source_commit") != identity["git_commit"]:
        raise RuntimeError(
            "recovery script commit differs from the frozen evaluation source commit"
        )

    changed_paths = (
        Path(runner.OUTPUT_PATHS["qa_raw"]),
        Path(runner.RESTRICTED_OUTPUT_PATHS["qa_full_raw"]),
        Path(runner.OUTPUT_PATHS["finder_raw"]),
        Path(runner.RESTRICTED_OUTPUT_PATHS["finder_full_raw"]),
    )
    payloads, normalization = prepare_normalized_payloads(*changed_paths)
    original_inventory = archive_originals(
        archive_dir,
        log_path,
        changed_paths,
        pre_manifest_paths,
        restricted_paths,
    )
    for path, payload in payloads.items():
        write_bytes_atomic(path, payload)

    with tempfile.TemporaryDirectory(
        prefix="ttlab-eval-v2-finalize-", dir=runtime_tmp
    ) as temp_name:
        temp_db = runner.initialize_temporary_database(Path(temp_name))
        from app.db import create_db_and_tables, engine
        from app.ingestion.generation_reconciler import reconcile_generation_links
        from sqlmodel import Session

        create_db_and_tables()
        with Session(engine) as session:
            reconciliation = reconcile_generation_links(
                session,
                project_root=root,
                extraction_dir=root / "data" / "extracted_text",
                chunks_dir=root / "data" / "chunks",
                pdf_dir=root / "data" / "pdfs",
            )
            keyword_index, corpus_identity = runner.prepare_temporary_keyword_index(
                session,
                generation_reconciliation=reconciliation,
            )
        runner.build_manifest(receipt, temp_db, keyword_index, corpus_identity)

    manifest_path = Path(runner.OUTPUT_PATHS["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["post_evaluation_finalization"] = {
        "status": "completed_without_case_reexecution",
        "reason": (
            "Manifest assembly rejected a redundant corpus_identity.scope field and the Finder "
            "backend serialized cited chunks rather than the complete paired-retrieval locator "
            "set in source_identity."
        ),
        "evaluation_reexecuted": False,
        "case_outputs_rescored": False,
        "labels_or_metrics_changed": False,
        "normalization": (
            "removed redundant corpus_identity.scope=technical and made Finder source_identity "
            "equal the complete serialized paired-retrieval locator set"
        ),
        "files": normalization,
        "evaluate_log_sha256": original_inventory["evaluation_log"]["sha256"],
        "finalizer_identity": identity,
        "finalized_at": datetime.now(UTC).isoformat(),
    }
    runner.write_json(manifest_path, manifest)
    validation = runner.invoke_locked_validator("--write-attestation")
    if validation.get("identity") != receipt.get("locked_validator_identity"):
        raise RuntimeError("recovery validation used a different locked environment")
    if (validation.get("report") or {}).get("restricted_raw_files_checked") is not True:
        raise RuntimeError("recovery validator did not strictly recompute restricted raw outputs")
    attestation_path = Path(runner.VALIDATION_ATTESTATION_PATH)
    require_regular_file(attestation_path, "strict validation attestation")

    recovery_receipt = {
        "status": "PASS",
        "recovery_contract": "exact_known_v2_manifest_runtime_provenance_mismatch_only",
        "evaluation_reexecuted": False,
        "case_outputs_rescored": False,
        "labels_or_metrics_changed": False,
        "evaluation_source_commit": receipt["evaluation_source_commit"],
        "finalizer_identity": identity,
        "evaluation_log_sha256": original_inventory["evaluation_log"]["sha256"],
        "normalization": normalization,
        "manifest_sha256": sha256_file(manifest_path),
        "validation_attestation_sha256": sha256_file(attestation_path),
        "locked_validator_identity": validation["identity"],
    }
    write_json_atomic(archive_dir / "manifest_recovery_receipt.json", recovery_receipt)
    return recovery_receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--root", type=Path, required=True, help="detached reproduction source root")
    value.add_argument(
        "--work-dir", type=Path, required=True, help="isolated reproduction workspace"
    )
    return value


def main() -> None:
    args = parser().parse_args()
    print(json.dumps(finalize(args.root, args.work_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
