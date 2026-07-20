#!/usr/bin/env python3
"""Retain verified, content-free attestations from an isolated reproduction run."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.reproducibility.manifest import (
    sha256_path,
    verify_manifest_and_checksums,
)


LOCAL_PATH = re.compile(r"(?:/(?:home|mnt|root|tmp)/|[A-Za-z]:\\Users\\)")
MANIFEST_NAME = "reproduction_manifest.json"
CHECKSUM_NAME = "REPRODUCTION_SHA256SUMS"
SUMMARY_NAME = "RETAINED_EVIDENCE.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read reproduction manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Reproduction manifest must be a JSON object")
    return value


def _assert_content_free_attestation(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if LOCAL_PATH.search(text):
        raise ValueError(f"Attestation contains an absolute local path: {path.name}")


def _release_attestations(manifest: dict[str, Any], work: Path) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for row in manifest.get("files", []):
        relative = str(row.get("path") or "")
        if not (
            relative.startswith("artifacts/release_bundle/")
            or relative.startswith("artifacts/reproduced_release_bundle/")
        ):
            continue
        if not relative.endswith((".manifest.json", ".sha256")):
            continue
        source = work / relative
        if not source.is_file() or sha256_path(source) != row.get("sha256"):
            raise ValueError(f"Release attestation is missing or changed: {relative}")
        _assert_content_free_attestation(source)
        retained.append(
            {
                "path": relative,
                "bytes": int(row.get("bytes") or 0),
                "sha256": str(row.get("sha256") or ""),
            }
        )
    return retained


def retain_evidence(
    *,
    work: Path,
    output_dir: Path,
    expected_commit: str,
    expected_tree: str,
    require_full: bool = True,
) -> dict[str, Any]:
    work = work.resolve()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(work):
        raise ValueError("Retained evidence directory must be outside the isolated reproduction workspace")
    manifest_path = work / MANIFEST_NAME
    checksum_path = work / CHECKSUM_NAME
    manifest = _load_json(manifest_path)

    snapshot = manifest.get("source_snapshot") or {}
    if manifest.get("status") != "completed":
        raise ValueError("Reproduction manifest is not completed")
    if require_full and manifest.get("mode") != "full":
        raise ValueError("Only a full reproduction may be retained as candidate evidence")
    if snapshot.get("commit") != expected_commit or manifest.get("source_commit") != expected_commit:
        raise ValueError("Reproduction source commit does not match the selected candidate")
    if snapshot.get("tree") != expected_tree:
        raise ValueError("Reproduction source tree does not match the selected candidate")
    if snapshot.get("clean_before_execution") is not True:
        raise ValueError("Reproduction did not start from a clean source snapshot")

    verification = verify_manifest_and_checksums(
        manifest,
        manifest_path,
        checksum_path,
        work,
    )
    _assert_content_free_attestation(manifest_path)
    _assert_content_free_attestation(checksum_path)
    release_attestations = _release_attestations(manifest, work)
    release_archives = [
        {
            "path": str(row.get("path")),
            "bytes": int(row.get("bytes") or 0),
            "sha256": str(row.get("sha256") or ""),
            "retained_in_reproduction_workspace": True,
            "committed_to_repository": False,
        }
        for row in manifest.get("files", [])
        if str(row.get("path") or "").startswith(
            ("artifacts/release_bundle/", "artifacts/reproduced_release_bundle/")
        )
        and str(row.get("path") or "").endswith(".tar.gz")
    ]
    summary = {
        "schema_version": 1,
        "status": "retained_verified",
        "mode": manifest.get("mode"),
        "generated_at": manifest.get("generated_at"),
        "source_snapshot": snapshot,
        "manifest": {
            "path": MANIFEST_NAME,
            "sha256": sha256_path(manifest_path),
        },
        "checksum_inventory": {
            "path": CHECKSUM_NAME,
            "sha256": sha256_path(checksum_path),
        },
        "verification": verification,
        "workspace_file_count": manifest.get("file_count"),
        "restricted_runtime_payload_count": manifest.get("restricted_runtime_payload_count"),
        "environment": manifest.get("environment"),
        "release_archives": release_archives,
        "retained_release_attestations": release_attestations,
        "rights_boundary": (
            "This retained evidence contains hashes, counts, relative paths, and sanitized release attestations only. "
            "It does not redistribute PDFs, extracted/chunk text, the live database, vector indexes, or model files."
        ),
        "claim_boundary": manifest.get("claim_boundary"),
    }

    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite retained evidence directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        shutil.copyfile(manifest_path, staging / MANIFEST_NAME)
        shutil.copyfile(checksum_path, staging / CHECKSUM_NAME)
        release_dir = staging / "release_attestations"
        if release_attestations:
            release_dir.mkdir()
        for row in release_attestations:
            source = work / row["path"]
            destination = release_dir / Path(row["path"]).name
            if destination.exists():
                raise ValueError(f"Duplicate release attestation name: {destination.name}")
            shutil.copyfile(source, destination)
        (staging / SUMMARY_NAME).write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        for path in staging.rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        os.replace(staging, output_dir)
        parent_fd = os.open(output_dir.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument(
        "--allow-quick",
        action="store_true",
        help="Retain a quick-run attestation; it must not be used as full-corpus evidence.",
    )
    args = parser.parse_args()
    summary = retain_evidence(
        work=args.work_dir,
        output_dir=args.out_dir,
        expected_commit=args.expected_commit,
        expected_tree=args.expected_tree,
        require_full=not args.allow_quick,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
