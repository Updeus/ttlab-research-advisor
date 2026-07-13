from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from app.reproducibility.release import sanitize_json, scan_payload, should_include


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


def test_payload_scanner_detects_secrets_absolute_paths_and_pdf_magic() -> None:
    content = b"/home/person/private\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
    findings = scan_payload(PurePosixPath("notes.txt"), content)
    assert "absolute_local_path" in findings
    assert "bearer_token" in findings
    assert "embedded_pdf" in scan_payload(PurePosixPath("fake.bin"), b"%PDF-1.7")


def test_sanitized_value_remains_json_serializable() -> None:
    sanitized, _ = sanitize_json({"answer": "source-like output", "score": 0.5})
    assert json.loads(json.dumps(sanitized))["score"] == 0.5
