from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from app.reproducibility.release import build_release, sanitize_json, scan_payload, should_include, verify_release


def test_release_policy_excludes_runtime_corpus_and_all_pdfs() -> None:
    assert should_include(Path("data/pdfs/paper.pdf"))[0] is False
    assert should_include(Path("build/thesis.pdf"))[0] is False
    assert should_include(Path("data/papers.db"))[0] is False
    assert should_include(Path("backend/app/main.py"))[0] is True


def test_json_sanitizer_hashes_source_text_and_local_paths() -> None:
    value = {
        "supporting_sources": [{"text": "restricted passage", "chunk_id": "c1"}],
        "local_pdf_path": "/mnt/c/private/paper.pdf",
        "label": "supported",
    }
    sanitized, events = sanitize_json(value)
    assert sanitized["supporting_sources"][0]["text"]["release_redacted"] is True
    assert sanitized["local_pdf_path"]["reason"] == "local_or_restricted_corpus_path"
    assert sanitized["label"] == "supported"
    assert len(events) == 2


def test_json_sanitizer_redacts_unclassified_text_fields_conservatively() -> None:
    sanitized, events = sanitize_json({"answer_point_judgments": [{"text": "publication-derived wording"}]})
    assert sanitized["answer_point_judgments"][0]["text"]["release_redacted"] is True
    assert events[0]["reason"] == "source_or_answer_text_not_redistributed"


def test_payload_scanner_detects_secrets_absolute_paths_and_pdf_magic() -> None:
    content = b"/home/person/private\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
    findings = scan_payload(PurePosixPath("notes.txt"), content)
    assert "absolute_local_path" in findings
    assert "bearer_token" in findings
    assert "embedded_pdf" in scan_payload(PurePosixPath("fake.bin"), b"%PDF-1.7")


def test_sanitized_value_remains_json_serializable() -> None:
    sanitized, _ = sanitize_json({"answer": "source-like output", "score": 0.5})
    assert json.loads(json.dumps(sanitized))["score"] == 0.5


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_release_is_deterministic_and_verifies_every_payload_checksum(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "backend/app").mkdir(parents=True)
    (root / "data/seed").mkdir(parents=True)
    (root / "backend/app/main.py").write_text("print('safe')\n")
    (root / "README.md").write_text("reproducible\n")
    (root / ".gitignore").write_text("build/\n")
    (root / "data/seed/papers.json").write_text(
        json.dumps([{"paper_id": "p1", "title": "Allowed metadata", "pdf_path": "/private/p1.pdf"}])
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")

    output_root = root / "build/releases"
    first = build_release(root=root, output_root=output_root, version="test")
    archive = output_root / first["archive"]["path"]
    first_sha = first["archive"]["sha256"]
    result = verify_release(archive)
    assert result["checksum_entries_verified"] >= 3
    assert first["source_worktree_dirty"] is False
    assert len(first["source_tree"]) == 40
    assert first["archive_verification"]["status"] == "valid"
    second = build_release(root=root, output_root=output_root, version="test")
    assert second["archive"]["sha256"] == first_sha
    assert second["generated_at"] == first["generated_at"]


def test_release_verifier_rejects_tampered_payload_even_when_content_scan_is_clean(tmp_path: Path) -> None:
    archive_path = tmp_path / "tampered.tar.gz"
    root = "release"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content in {
            f"{root}/README.md": b"changed but superficially safe\n",
            f"{root}/SHA256SUMS": ("0" * 64 + "  README.md\n").encode(),
            f"{root}/RELEASE_MANIFEST.json": b"{}\n",
        }.items():
            path = tmp_path / Path(name).name
            path.write_bytes(content)
            archive.add(path, arcname=name)
    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        verify_release(archive_path)
