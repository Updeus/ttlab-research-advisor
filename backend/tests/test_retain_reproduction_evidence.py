from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.reproducibility.manifest import manifest, write_manifest_and_checksums


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "retain_reproduction_evidence",
    ROOT / "scripts" / "retain_reproduction_evidence.py",
)
assert SPEC is not None and SPEC.loader is not None
RETAINER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETAINER)


def build_completed_run(tmp_path: Path, *, mode: str = "full") -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    work = tmp_path / "run"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend/requirements-lock.txt").write_text("example==1.0\n", encoding="utf-8")
    (root / "frontend/package-lock.json").write_text("{}\n", encoding="utf-8")
    (work / "logs").mkdir(parents=True)
    (work / "logs/tests.log").write_text("passed\n", encoding="utf-8")
    release = work / "artifacts/release_bundle"
    release.mkdir(parents=True)
    (release / "candidate.tar.gz").write_bytes(b"sanitized archive")
    (release / "candidate.manifest.json").write_text('{"status":"valid"}\n', encoding="utf-8")
    (release / "candidate.sha256").write_text("a" * 64 + "  candidate.tar.gz\n", encoding="utf-8")
    commit = "a" * 40
    tree = "b" * 40
    value = manifest(
        root,
        work,
        mode,
        source_commit=commit,
        source_tree=tree,
        source_clean_at_start=True,
    )
    write_manifest_and_checksums(value, work / RETAINER.MANIFEST_NAME, work)
    return work, commit, tree


def test_retain_verified_full_run_without_runtime_payloads(tmp_path: Path) -> None:
    work, commit, tree = build_completed_run(tmp_path)
    output = tmp_path / "retained"

    summary = RETAINER.retain_evidence(
        work=work,
        output_dir=output,
        expected_commit=commit,
        expected_tree=tree,
    )

    assert summary["status"] == "retained_verified"
    assert summary["source_snapshot"]["commit"] == commit
    assert summary["release_archives"][0]["committed_to_repository"] is False
    assert (output / RETAINER.MANIFEST_NAME).is_file()
    assert (output / RETAINER.CHECKSUM_NAME).is_file()
    assert (output / "release_attestations/candidate.manifest.json").is_file()
    assert (output / "release_attestations/candidate.sha256").is_file()
    persisted = json.loads((output / RETAINER.SUMMARY_NAME).read_text(encoding="utf-8"))
    assert persisted == summary
    assert not (output / "candidate.tar.gz").exists()


def test_retain_rejects_wrong_revision_quick_mode_and_overwrite(tmp_path: Path) -> None:
    work, commit, tree = build_completed_run(tmp_path, mode="quick")
    with pytest.raises(ValueError, match="full reproduction"):
        RETAINER.retain_evidence(
            work=work,
            output_dir=tmp_path / "retained",
            expected_commit=commit,
            expected_tree=tree,
        )
    with pytest.raises(ValueError, match="source commit"):
        RETAINER.retain_evidence(
            work=work,
            output_dir=tmp_path / "retained",
            expected_commit="c" * 40,
            expected_tree=tree,
            require_full=False,
        )

    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError, match="overwrite"):
        RETAINER.retain_evidence(
            work=work,
            output_dir=output,
            expected_commit=commit,
            expected_tree=tree,
            require_full=False,
        )


def test_retain_rejects_absolute_local_paths(tmp_path: Path) -> None:
    work, commit, tree = build_completed_run(tmp_path)
    manifest_path = work / RETAINER.MANIFEST_NAME
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    value["claim_boundary"] = "/home/example/private"
    write_manifest_and_checksums(value, manifest_path, work)

    with pytest.raises(ValueError, match="absolute local path"):
        RETAINER.retain_evidence(
            work=work,
            output_dir=tmp_path / "retained",
            expected_commit=commit,
            expected_tree=tree,
        )
