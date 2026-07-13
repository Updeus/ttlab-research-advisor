from __future__ import annotations

from pathlib import Path

from app.reproducibility.manifest import manifest


def test_manifest_hashes_outputs_and_marks_private_runtime_payloads(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    work = root / "tmp/run"
    (work / "logs").mkdir(parents=True)
    (work / "data/pdfs").mkdir(parents=True)
    (work / "logs/test.log").write_text("passed\n")
    (work / "data/pdfs/paper.pdf").write_bytes(b"%PDF-test")
    result = manifest(root, work, "quick")
    assert result["file_count"] == 2
    assert result["restricted_runtime_payload_count"] == 1
    assert all(row["sha256"] for row in result["files"])
