from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from app.reproducibility.release import (
    CANONICAL_V2_RELEASE_FILES,
    build_release,
    sanitize_json,
    sanitize_json_bytes,
    scan_payload,
    should_include,
    validate_canonical_v2_for_release,
    verify_release,
)


def test_release_policy_excludes_runtime_corpus_and_all_pdfs() -> None:
    assert should_include(Path("data/pdfs/paper.pdf"))[0] is False
    assert should_include(Path("build/thesis.pdf"))[0] is False
    assert should_include(Path("data/papers.db"))[0] is False
    assert should_include(Path("thesis/figures/screenshots/ask-answer.png")) == (
        False,
        "source_bearing_interface_screenshot",
    )
    assert should_include(Path("artifacts/peer_review_remediation/v2/manifest_v2.json")) == (
        True,
        None,
    )
    assert should_include(Path("artifacts/peer_review_remediation/v2/extra.json")) == (
        False,
        "unapproved_canonical_v2_artifact",
    )
    assert should_include(Path("artifacts/peer_review_remediation/v2/qa_full_raw_v2.jsonl")) == (
        False,
        "rights_sensitive_v2_raw_output",
    )
    assert should_include(
        Path("artifacts/reproduction/peer_review_remediation/v2/manifest_v2.json")
    ) == (False, "noncanonical_v2_artifact_path")
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


def test_json_sanitizer_redacts_sensitive_nested_lists_and_objects_as_one_attestation() -> None:
    sanitized, events = sanitize_json(
        {"claim": ["verbatim wording"], "future_work": {"excerpt": "derived wording"}}
    )
    assert sanitized["claim"]["release_redacted"] is True
    assert sanitized["future_work"]["release_redacted"] is True
    assert len(events) == 2


def test_release_sanitizer_recursively_redacts_real_v2_locator_anchors() -> None:
    evaluation_dir = Path(__file__).resolve().parents[2] / "data/evaluation"
    dataset_names = (
        "qa_selective_response_v2.jsonl",
        "finder_proxy_profiles_v2.jsonl",
        "topic_source_labels_v2.jsonl",
    )

    def anchors(value):
        if isinstance(value, dict):
            return [
                child
                for key, child in value.items()
                if key == "anchor"
            ] + [nested for child in value.values() for nested in anchors(child)]
        if isinstance(value, list):
            return [nested for child in value for nested in anchors(child)]
        return []

    for name in dataset_names:
        original_rows = [
            json.loads(line)
            for line in (evaluation_dir / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        original_anchors = anchors(original_rows)
        assert original_anchors and all(isinstance(value, str) and value for value in original_anchors)

        released, events = sanitize_json_bytes((evaluation_dir / name).read_bytes(), ".jsonl")
        released_rows = [json.loads(line) for line in released.decode("utf-8").splitlines()]
        released_anchors = anchors(released_rows)

        assert len(released_anchors) == len(original_anchors)
        assert all(
            value.get("release_redacted") is True
            and value.get("reason") == "source_or_answer_text_not_redistributed"
            for value in released_anchors
        )
        released_text = released.decode("utf-8")
        assert all(anchor not in released_text for anchor in original_anchors)
        assert sum(event["json_path"].endswith(".anchor") for event in events) == len(
            original_anchors
        )


def test_payload_scanner_detects_secrets_absolute_paths_and_pdf_magic() -> None:
    content = b"/home/person/private\nAuthorization: Bearer " + b"abcdefghijklmnopqrstuvwxyz\n"
    findings = scan_payload(PurePosixPath("notes.txt"), content)
    assert "absolute_local_path" in findings
    assert "bearer_token" in findings
    assert "embedded_pdf" in scan_payload(PurePosixPath("fake.bin"), b"%PDF-1.7")


@pytest.mark.parametrize(
    "content",
    [
        b"/" + b"home/person/private",
        b"/" + b"mnt/c/private/file",
        b"/" + b"Users/person/private",
        b"/" + b"root/private/file",
        b"/" + b"tmp/private/file",
        b"C:" + b"\\Users\\person\\private",
    ],
)
def test_payload_scanner_rejects_common_local_workspace_roots(content: bytes) -> None:
    assert "absolute_local_path" in scan_payload(PurePosixPath("notes.txt"), content)


@pytest.mark.parametrize(
    "content",
    [
        b"file:///home/person/private",
        b"/workspace/project/private",
        b"/Volumes/Users/person/private",
        b"D:/Users/person/private",
        b"\\\\server\\share\\private",
    ],
)
def test_payload_scanner_rejects_extended_absolute_path_forms(content: bytes) -> None:
    assert "absolute_local_path" in scan_payload(PurePosixPath("notes.txt"), content)


def test_v2_release_topology_rejects_partial_noncanonical_and_full_raw() -> None:
    canonical_prefix = Path("artifacts/peer_review_remediation/v2")
    with pytest.raises(RuntimeError, match="incomplete or unapproved"):
        validate_canonical_v2_for_release([canonical_prefix / "manifest_v2.json"])
    with pytest.raises(RuntimeError, match="noncanonical"):
        validate_canonical_v2_for_release(
            [Path("artifacts/reproduction/peer_review_remediation/v2/manifest_v2.json")]
        )
    with pytest.raises(RuntimeError, match="rights-sensitive"):
        validate_canonical_v2_for_release(
            [canonical_prefix / "qa_full_raw_v2.jsonl"]
        )
    assert len(CANONICAL_V2_RELEASE_FILES) == 17


@pytest.mark.parametrize("entry_kind", ["directory", "symlink"])
def test_v2_release_topology_rejects_non_file_entries(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    package = tmp_path / "artifacts/peer_review_remediation/v2"
    package.mkdir(parents=True)
    for filename in CANONICAL_V2_RELEASE_FILES:
        (package / filename).write_text("{}\n", encoding="utf-8")
    unexpected = package / "nested"
    if entry_kind == "directory":
        unexpected.mkdir()
        (unexpected / "payload.json").write_text("{}\n", encoding="utf-8")
    else:
        unexpected.symlink_to(package / "manifest_v2.json")
    tracked = [
        Path("artifacts/peer_review_remediation/v2") / filename
        for filename in CANONICAL_V2_RELEASE_FILES
    ]

    with pytest.raises(RuntimeError, match="flat and contain regular files only"):
        validate_canonical_v2_for_release(tracked, root=tmp_path)


def test_v2_release_topology_rejects_unexpected_regular_file(tmp_path: Path) -> None:
    package = tmp_path / "artifacts/peer_review_remediation/v2"
    package.mkdir(parents=True)
    for filename in CANONICAL_V2_RELEASE_FILES:
        (package / filename).write_text("{}\n", encoding="utf-8")
    (package / "unexpected.json").write_text("{}\n", encoding="utf-8")
    tracked = [
        Path("artifacts/peer_review_remediation/v2") / filename
        for filename in CANONICAL_V2_RELEASE_FILES
    ]

    with pytest.raises(RuntimeError, match="filesystem inventory is incomplete or unapproved"):
        validate_canonical_v2_for_release(tracked, root=tmp_path)


def test_v2_release_claim_requires_successful_versionable_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = tmp_path / "data/evaluation/validate_peer_review_remediation_v2.py"
    validator.parent.mkdir(parents=True)
    validator.write_text("# validator fixture\n", encoding="utf-8")
    package = tmp_path / "artifacts/peer_review_remediation/v2"
    package.mkdir(parents=True)
    for filename in CANONICAL_V2_RELEASE_FILES:
        (package / filename).write_text("{}\n", encoding="utf-8")
    tracked = [
        Path("artifacts/peer_review_remediation/v2") / filename
        for filename in sorted(CANONICAL_V2_RELEASE_FILES)
    ]
    monkeypatch.setattr(
        "app.reproducibility.release.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "pass",
                    "mode": "completed_versionable_package",
                    "evaluation_source_commit": "a" * 40,
                    "package_file_count": 17,
                    "rights_sensitive_raw_text_in_versionable_package": False,
                }
            ),
            stderr="",
        ),
    )

    report = validate_canonical_v2_for_release(tracked, root=tmp_path)

    assert report["status"] == "validated"
    assert report["versionable_no_sensitive_text_claimed"] is True


def test_sanitized_value_remains_json_serializable() -> None:
    sanitized, _ = sanitize_json({"answer": "source-like output", "score": 0.5})
    assert json.loads(json.dumps(sanitized))["score"] == 0.5


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_release_is_deterministic_and_verifies_every_payload_checksum(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "backend/app").mkdir(parents=True)
    (root / "frontend").mkdir(parents=True)
    (root / "data/seed").mkdir(parents=True)
    (root / "artifacts/phase4/recommendation_proxy_v1").mkdir(parents=True)
    (root / "thesis/figures/screenshots").mkdir(parents=True)
    (root / "backend/app/main.py").write_text("print('safe')\n")
    (root / "backend/requirements-lock.txt").write_text("safe==1.0\n")
    (root / "frontend/package-lock.json").write_text("{}\n")
    (root / "README.md").write_text("reproducible\n")
    (root / ".gitignore").write_text("build/\n")
    (root / "data/seed/papers.json").write_text(
        json.dumps([{"paper_id": "p1", "title": "Allowed metadata", "pdf_path": "/private/p1.pdf"}])
    )
    (root / "artifacts/phase4/recommendation_proxy_v1/raw_outputs.jsonl").write_text(
        json.dumps({"claim": "derived claim wording", "paper_focus": "publication focus wording"}) + "\n",
        encoding="utf-8",
    )
    (root / "thesis/figures/screenshots/answer.png").write_bytes(
        b"binary screenshot containing rendered restricted passage"
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
    with tarfile.open(archive, "r:gz") as bundle:
        assert not any("figures/screenshots" in item.name for item in bundle.getmembers())
        member = next(item for item in bundle.getmembers() if item.name.endswith("/raw_outputs.jsonl"))
        extracted = bundle.extractfile(member)
        row = json.loads(extracted.read().decode("utf-8")) if extracted else {}
    assert row["claim"]["release_redacted"] is True
    assert row["paper_focus"]["release_redacted"] is True
    second = build_release(root=root, output_root=root / "build/releases-2", version="test")
    assert second["archive"]["sha256"] == first_sha
    assert second["generated_at"] == first["generated_at"]
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        build_release(root=root, output_root=output_root, version="test")


def test_validated_v2_package_is_released_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "source"
    (root / "backend/app").mkdir(parents=True)
    (root / "backend/app/main.py").write_text("print('safe')\n")
    (root / "backend/requirements-lock.txt").write_text("safe==1.0\n")
    (root / "frontend").mkdir(parents=True)
    (root / "frontend/package-lock.json").write_text("{}\n")
    (root / "README.md").write_text("safe\n")
    (root / ".gitignore").write_text("build/\n")
    package = root / "artifacts/peer_review_remediation/v2"
    package.mkdir(parents=True)
    expected: dict[str, bytes] = {}
    for filename in CANONICAL_V2_RELEASE_FILES:
        content = (
            b"% deterministic macro\n"
            if filename.endswith(".tex")
            else b'{"claim":"already-attested-structural-value"}\n'
        )
        (package / filename).write_bytes(content)
        expected[filename] = content
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    monkeypatch.setattr(
        "app.reproducibility.release.validate_canonical_v2_for_release",
        lambda *_args, **_kwargs: {
            "status": "validated",
            "package_file_count": 17,
            "versionable_no_sensitive_text_claimed": True,
        },
    )

    manifest = build_release(root=root, output_root=root / "build/releases", version="v2-bytes")
    archive_path = root / "build/releases" / manifest["archive"]["path"]
    with tarfile.open(archive_path, "r:gz") as archive:
        for filename, content in expected.items():
            member = next(
                item
                for item in archive.getmembers()
                if item.name.endswith(f"/artifacts/peer_review_remediation/v2/{filename}")
            )
            extracted = archive.extractfile(member)
            assert extracted is not None and extracted.read() == content


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


def test_release_verifier_rejects_self_consistent_checksums_with_false_manifest(tmp_path: Path) -> None:
    archive_path = tmp_path / "false-manifest.tar.gz"
    commit = "a" * 40
    root = f"ttlab-research-advisor-test-{commit[:12]}"
    readme = b"safe payload\n"
    checksums = f"{hashlib.sha256(readme).hexdigest()}  README.md\n".encode()
    manifest = {
        "schema_version": 1,
        "release_name": root,
        "version": "test",
        "prepared_tag": "vtest",
        "tag_created": False,
        "source_commit": commit,
        "source_tree": "b" * 40,
        "source_worktree_dirty": False,
        "generated_at": "2026-07-12T00:00:00+00:00",
        "included_file_count": 3,
        "sanitization_event_count": 0,
        "files": [
            {
                "path": "README.md",
                "source_path": "README.md",
                "source_sha256": "c" * 64,
                "released_sha256": hashlib.sha256(readme).hexdigest(),
                "bytes": 999,
                "sanitization_event_count": 0,
            }
        ],
        "dependency_locks": {
            "python": {"path": "missing", "source_sha256": None, "sha256": None},
            "frontend": {"path": "missing", "source_sha256": None, "sha256": None},
        },
    }
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content in {
            f"{root}/README.md": readme,
            f"{root}/SHA256SUMS": checksums,
            f"{root}/RELEASE_MANIFEST.json": (json.dumps(manifest) + "\n").encode(),
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    with pytest.raises(RuntimeError, match="embedded_manifest:payload_size_mismatch"):
        verify_release(archive_path)
