from __future__ import annotations

from pathlib import Path

import pytest

from app.reproducibility.manifest import manifest, verify_manifest_and_checksums, write_manifest_and_checksums


def test_manifest_hashes_outputs_and_marks_private_runtime_payloads(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    work = root / "tmp/run"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir(parents=True)
    (root / "backend/requirements-lock.txt").write_text("example==1.0\n")
    (root / "frontend/package-lock.json").write_text("{}\n")
    (work / "logs").mkdir(parents=True)
    (work / "data/pdfs").mkdir(parents=True)
    (work / "logs/test.log").write_text("passed\n")
    (work / "data/pdfs/paper.pdf").write_bytes(b"%PDF-test")
    (work / ".venv/lib").mkdir(parents=True)
    (work / ".venv/lib/ignored.py").write_text("ignored\n")
    (work / "source").mkdir()
    (work / "source/.git").write_text("gitdir: /outside/worktree\n")
    result = manifest(
        root,
        work,
        "quick",
        source_commit="a" * 40,
        source_tree="b" * 40,
        source_clean_at_start=True,
    )
    assert result["file_count"] == 2
    assert result["restricted_runtime_payload_count"] == 1
    assert result["excluded_runtime_directories"] == [".venv"]
    assert result["excluded_runtime_files"] == ["source/.git"]
    assert all(row["path"] != "source/.git" for row in result["files"])
    assert all(row["sha256"] for row in result["files"])
    assert result["work_directory"] == "."
    assert result["source_snapshot"] == {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "construction": "detached_git_worktree",
        "clean_before_execution": True,
    }
    assert result["post_execution_worktree"]["dirty"] is False
    assert len(result["environment"]["dependency_locks"]["python"]["sha256"]) == 64

    output = work / "reproduction_manifest.json"
    checksum_path = write_manifest_and_checksums(result, output, work)
    checksums = checksum_path.read_text().splitlines()
    assert any(line.endswith("  logs/test.log") for line in checksums)
    assert any(line.endswith("  reproduction_manifest.json") for line in checksums)
    assert verify_manifest_and_checksums(result, output, checksum_path, work) == {
        "status": "valid",
        "inventory_files": 2,
        "checksum_entries": 3,
    }

    (work / "logs/test.log").write_text("changed after manifest\n")
    with pytest.raises(ValueError, match="inventory changed"):
        verify_manifest_and_checksums(result, output, checksum_path, work)
