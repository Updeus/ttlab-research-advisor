from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VERSION = "0.1.0-remediation"
DEFAULT_OUTPUT_ROOT = ROOT / "build/releases"
INCLUDED_TOP_LEVEL = {
    ".gitignore",
    "AGENTS.md",
    "AUTHOR_REVIEW.md",
    "Makefile",
    "README.md",
    "artifacts",
    "backend",
    "data",
    "docs",
    "frontend",
    "paper",
    "pyproject.toml",
    "scripts",
    "thesis",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "playwright-report",
    "private",
    "raw",
    "test-results",
    "tmp",
}
EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pdf", ".pyc", ".pyo", ".pem", ".key"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "narine-rtsi.pdf"}
TEXT_BEARING_KEYS = {
    "answer",
    "anchor",
    "baseline_work",
    "claim",
    "chunk_text",
    "context",
    "corrected_text",
    "evidence_summary",
    "evaluation_plan",
    "extension_summary",
    "extension_title",
    "future_work",
    "identified_gap",
    "license_evidence_excerpt",
    "mvp_scope",
    "page_text",
    "paper_focus",
    "problem",
    "raw_prompt",
    "review_note",
    "snippet",
    "source_excerpt",
    "source_text",
    "why_it_fits_student",
}
LOCAL_PATH_PATTERN = re.compile(
    r"(?:file:///(?:home|mnt|tmp|root|Users|workspace|workspaces|Volumes|private/var/folders)/"
    r"|(?<![A-Za-z0-9:])/(?:home|mnt|tmp|root|Users|workspace|workspaces|Volumes|private/var/folders)/"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    r"|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer_token": re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{16,}"),
}
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_FILE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 500 * 1024 * 1024
CANONICAL_V2_PARTS = ("artifacts", "peer_review_remediation", "v2")
CANONICAL_V2_RELEASE_FILES = frozenset(
    {
        "freeze_receipt_v2.json",
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
        "manifest_v2.json",
        "validation_attestation_v2.json",
    }
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str, root: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def tracked_paths(root: Path = ROOT) -> list[Path]:
    values = git("ls-files", "-z", root=root).split("\0")
    return [Path(value) for value in values if value]


def validate_canonical_v2_for_release(
    tracked: list[Path],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Fail closed on noncanonical v2 material and attest a complete package."""

    package_dir = root.joinpath(*CANONICAL_V2_PARTS)
    filesystem_names: set[str] = set()
    if package_dir.exists() or package_dir.is_symlink():
        if package_dir.is_symlink() or not package_dir.is_dir():
            raise RuntimeError("Canonical v2 package must be a real directory, not a symlink")
        for entry in package_dir.iterdir():
            if entry.is_symlink() or not entry.is_file():
                raise RuntimeError(
                    "Canonical v2 package must be flat and contain regular files only: "
                    f"{entry.relative_to(root).as_posix()}"
                )
            filesystem_names.add(entry.name)

    canonical = {
        path.name
        for path in tracked
        if path.parts[:3] == CANONICAL_V2_PARTS and len(path.parts) == 4
    }
    for path in tracked:
        parts = path.parts
        v2_marker = any(
            parts[index : index + 2] == ("peer_review_remediation", "v2")
            for index in range(len(parts) - 1)
        )
        if "full_raw" in path.name.lower() and (v2_marker or "v2" in path.name.lower()):
            raise RuntimeError(f"Release rejected rights-sensitive v2 raw output: {path.as_posix()}")
        if parts[:3] == CANONICAL_V2_PARTS and (
            len(parts) != 4 or path.name not in CANONICAL_V2_RELEASE_FILES
        ):
            raise RuntimeError(f"Release rejected unapproved canonical v2 artifact: {path.as_posix()}")
        if v2_marker and parts[:3] != CANONICAL_V2_PARTS:
            raise RuntimeError(f"Release rejected noncanonical v2 package path: {path.as_posix()}")
    if not canonical:
        if filesystem_names:
            raise RuntimeError(
                "Canonical v2 package exists but its files are not tracked for release"
            )
        return {
            "status": "not_present",
            "versionable_no_sensitive_text_claimed": False,
        }
    if canonical != CANONICAL_V2_RELEASE_FILES:
        raise RuntimeError(
            "Canonical v2 release inventory is incomplete or unapproved: "
            f"missing={sorted(CANONICAL_V2_RELEASE_FILES - canonical)}, "
            f"unexpected={sorted(canonical - CANONICAL_V2_RELEASE_FILES)}"
        )
    if filesystem_names != CANONICAL_V2_RELEASE_FILES:
        raise RuntimeError(
            "Canonical v2 filesystem inventory is incomplete or unapproved: "
            f"missing={sorted(CANONICAL_V2_RELEASE_FILES - filesystem_names)}, "
            f"unexpected={sorted(filesystem_names - CANONICAL_V2_RELEASE_FILES)}"
        )
    validator = root / "data" / "evaluation" / "validate_peer_review_remediation_v2.py"
    if not validator.is_file():
        raise RuntimeError("Canonical v2 package exists but its validator is missing")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "backend")
    completed = subprocess.run(
        [sys.executable, str(validator), "--versionable-only"],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no validator output"
        raise RuntimeError(f"Canonical v2 package validation failed before release: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Canonical v2 package validator returned invalid JSON") from exc
    if (
        report.get("status") != "pass"
        or report.get("mode") != "completed_versionable_package"
        or report.get("rights_sensitive_raw_text_in_versionable_package") is not False
    ):
        raise RuntimeError("Canonical v2 package validator did not establish the bounded release claim")
    return {
        "status": "validated",
        "validator_mode": report["mode"],
        "evaluation_source_commit": report.get("evaluation_source_commit"),
        "package_file_count": report.get("package_file_count"),
        "versionable_no_sensitive_text_claimed": True,
        "restricted_raw_validation": (
            "recorded by the strict full-validation attestation; not independently "
            "rechecked during release validation"
        ),
    }


def should_include(relative: Path) -> tuple[bool, str | None]:
    parts = relative.parts
    if not parts or parts[0] not in INCLUDED_TOP_LEVEL:
        return False, "outside_release_allowlist"
    if EXCLUDED_PARTS.intersection(parts):
        return False, "restricted_or_generated_directory"
    if relative.name in EXCLUDED_NAMES or relative.name.startswith(".env"):
        return False, "secret_or_local_configuration"
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False, "restricted_or_binary_extension"
    if parts[:2] in {("data", "pdfs"), ("data", "extracted_text"), ("data", "chunks"), ("data", "indexes"), ("data", "generated")}:
        return False, "restricted_runtime_corpus"
    if parts[:3] == ("thesis", "figures", "screenshots"):
        return False, "source_bearing_interface_screenshot"
    if parts[:2] == ("artifacts", "baseline"):
        return False, "local_baseline_environment"
    if parts[:3] == ("artifacts", "phase6", "release"):
        return False, "release_attestation_output"
    if "full_raw" in relative.name.lower():
        return False, "rights_sensitive_v2_raw_output"
    if parts[:3] == CANONICAL_V2_PARTS:
        if len(parts) != 4 or relative.name not in CANONICAL_V2_RELEASE_FILES:
            return False, "unapproved_canonical_v2_artifact"
        return True, None
    if any(parts[index : index + 2] == ("peer_review_remediation", "v2") for index in range(len(parts) - 1)):
        return False, "noncanonical_v2_artifact_path"
    return True, None


def redaction(value: str, reason: str) -> dict[str, Any]:
    return {
        "release_redacted": True,
        "reason": reason,
        "original_sha256": sha256_bytes(value.encode("utf-8")),
        "original_length": len(value),
    }


def sanitize_json(value: Any, *, path: tuple[str, ...] = ()) -> tuple[Any, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            next_path = (*path, str(key))
            lowered = str(key).lower()
            if lowered in {"local_pdf_path", "extracted_json_path", "extracted_text_path", "pdf_path"} and item:
                rendered = str(item)
                sanitized[key] = redaction(rendered, "local_or_restricted_corpus_path")
                events.append({"json_path": ".".join(next_path), "reason": "local_or_restricted_corpus_path"})
                continue
            if lowered in {"raw_record", "raw_scraped"} and item:
                rendered = json.dumps(item, sort_keys=True, ensure_ascii=False)
                sanitized[key] = redaction(rendered, "unreviewed_scrape_payload")
                events.append({"json_path": ".".join(next_path), "reason": "unreviewed_scrape_payload"})
                continue
            if item is not None and (lowered in TEXT_BEARING_KEYS or lowered == "text"):
                rendered = item if isinstance(item, str) else json.dumps(item, sort_keys=True, ensure_ascii=False)
                sanitized[key] = redaction(rendered, "source_or_answer_text_not_redistributed")
                events.append({"json_path": ".".join(next_path), "reason": "source_or_answer_text_not_redistributed"})
                continue
            sanitized_item, child_events = sanitize_json(item, path=next_path)
            sanitized[key] = sanitized_item
            events.extend(child_events)
        return sanitized, events
    if isinstance(value, list):
        sanitized_list: list[Any] = []
        for index, item in enumerate(value):
            sanitized_item, child_events = sanitize_json(item, path=(*path, str(index)))
            sanitized_list.append(sanitized_item)
            events.extend(child_events)
        return sanitized_list, events
    if isinstance(value, str) and LOCAL_PATH_PATTERN.search(value):
        events.append({"json_path": ".".join(path), "reason": "absolute_local_path"})
        return redaction(value, "absolute_local_path"), events
    return value, events


def sanitize_json_bytes(content: bytes, suffix: str) -> tuple[bytes, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    if suffix == ".jsonl":
        rows: list[str] = []
        for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            sanitized, row_events = sanitize_json(value, path=(str(line_number),))
            rows.append(json.dumps(sanitized, sort_keys=True, ensure_ascii=False))
            events.extend(row_events)
        return ("\n".join(rows) + "\n").encode("utf-8"), events
    value = json.loads(content.decode("utf-8"))
    sanitized, events = sanitize_json(value)
    return (json.dumps(sanitized, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"), events


def sanitize_text_bytes(content: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content, []
    events: list[dict[str, Any]] = []
    if LOCAL_PATH_PATTERN.search(text):
        # A Windows drive-root replacement can reveal a second path-shaped
        # prefix (for example ``D:/Users`` -> ``/Users``). Iterate to a fixed
        # point so the post-sanitization scanner cannot rediscover it.
        while LOCAL_PATH_PATTERN.search(text):
            text = LOCAL_PATH_PATTERN.sub("<LOCAL_PATH_REDACTED>/", text)
        events.append({"reason": "absolute_local_path"})
    return text.encode("utf-8"), events


def scan_payload(path: PurePosixPath, content: bytes) -> list[str]:
    findings: list[str] = []
    lower_name = path.name.lower()
    if path.suffix.lower() in EXCLUDED_SUFFIXES or lower_name.startswith(".env"):
        findings.append("forbidden_file_type")
    if b"%PDF-" in content[:16]:
        findings.append("embedded_pdf")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return findings
    if LOCAL_PATH_PATTERN.search(text):
        findings.append("absolute_local_path")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(label)
    return sorted(set(findings))


def _sanitized_seed(content: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, list):
        return sanitize_json_bytes(content, ".json")
    allowed = {
        "paper_id",
        "title",
        "authors",
        "year",
        "publication_date_raw",
        "venue",
        "source_url",
        "post_url",
        "pdf_url",
        "doi",
        "keywords",
        "topics",
        "ingestion_status",
        "pdf_text_status",
    }
    rows = [{key: row.get(key) for key in sorted(allowed) if key in row} for row in value if isinstance(row, dict)]
    events = [{"reason": "seed_allowlist", "removed_fields": sorted(set().union(*(set(row) for row in value if isinstance(row, dict))) - allowed)}]
    return (json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"), events


def release_readme(version: str, commit: str) -> bytes:
    return f"""# TTLAB Research Intelligence Platform — sanitized reproducibility release

Version: `{version}`
Source commit: `{commit}`

This bundle contains source code, dependency locks, schemas, redistributable
metadata, sanitized evaluation records, aggregate/raw metric artifacts, prompts,
code-native figure sources, and reproduction instructions. First verify the unpacked
payload from this directory with `sha256sum -c SHA256SUMS`.

This tarball is not a Git worktree and therefore cannot preserve the detached-
commit checks performed by `make reproduce-quick` or `make reproduce`. To run
those one-command gates, obtain an authorized Git checkout, check out source
commit `{commit}`, install the tracked dependency locks, and then run the make
target. Full reproduction additionally requires separately authorized local
corpus inputs; those inputs are not supplied by this bundle.

The bundle intentionally excludes all PDFs, SQLite databases, extracted/chunk
text, vector indexes, interface screenshots, secrets, `.env` files, private
AI-review prompts, and raw Europe PMC XML. Screenshots are excluded as binary
files because they can contain rendered source or answer text that cannot be
field-sanitized. TTLAB project authorization does not establish permission to
redistribute every third-party publication. Fields containing source or answer
text in included JSON/JSONL records are replaced with hashes and lengths.

See `docs/DATA_AVAILABILITY_AND_RELEASE.md`, `RELEASE_MANIFEST.json`, and
`SHA256SUMS` for the precise boundary and file-level provenance.
""".encode("utf-8")


def build_release(
    *,
    root: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    version: str = DEFAULT_VERSION,
    allow_dirty: bool = False,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    commit = git("rev-parse", "HEAD", root=root)
    short_commit = commit[:12]
    commit_timestamp = int(git("show", "-s", "--format=%ct", commit, root=root))
    release_timestamp = datetime.fromtimestamp(commit_timestamp, UTC).isoformat()
    dirty_status = git("status", "--porcelain", root=root)
    if dirty_status and not allow_dirty:
        raise RuntimeError("Refusing to build a release from a dirty worktree; commit changes or pass --allow-dirty")
    tracked = tracked_paths(root)
    v2_validation = validate_canonical_v2_for_release(tracked, root=root)
    release_name = f"ttlab-research-advisor-{version}-{short_commit}"
    output_root.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / f"{release_name}.tar.gz"
    manifest_copy_path = output_root / f"{release_name}.manifest.json"
    checksum_path = output_root / f"{release_name}.sha256"
    existing_outputs = [path.name for path in (archive_path, manifest_copy_path, checksum_path) if path.exists()]
    if existing_outputs:
        raise FileExistsError(f"Refusing to overwrite existing release outputs: {existing_outputs}")
    excluded: list[dict[str, str]] = []
    entries: dict[PurePosixPath, bytes] = {}
    provenance: list[dict[str, Any]] = []
    total_redactions = 0

    for relative in sorted(tracked, key=lambda value: value.as_posix()):
        include, reason = should_include(relative)
        if not include:
            excluded.append({"path": relative.as_posix(), "reason": reason or "excluded"})
            continue
        source = root / relative
        if not source.is_file():
            continue
        original = source.read_bytes()
        events: list[dict[str, Any]] = []
        output_relative = relative
        if relative.parts[:3] == CANONICAL_V2_PARTS:
            # This exact allowlisted package has already passed the strict
            # versionable validator. Preserve its internal hash/attestation
            # graph byte-for-byte; the payload scanner still runs below.
            released = original
        elif relative.parts[:2] == ("data", "seed") and relative.suffix == ".json":
            released, events = _sanitized_seed(original)
            output_relative = Path("data/seed") / f"sanitized_{relative.name}"
        elif relative.suffix.lower() in {".json", ".jsonl"}:
            released, events = sanitize_json_bytes(original, relative.suffix.lower())
        else:
            released, events = sanitize_text_bytes(original)
        findings = scan_payload(PurePosixPath(output_relative.as_posix()), released)
        if findings:
            raise RuntimeError(f"Release scan rejected {output_relative}: {', '.join(findings)}")
        path = PurePosixPath(release_name) / PurePosixPath(output_relative.as_posix())
        entries[path] = released
        total_redactions += len(events)
        provenance.append(
            {
                "path": output_relative.as_posix(),
                "source_path": relative.as_posix(),
                "source_sha256": sha256_bytes(original),
                "released_sha256": sha256_bytes(released),
                "bytes": len(released),
                "sanitization_event_count": len(events),
            }
        )

    entries[PurePosixPath(release_name) / "REPRODUCE.md"] = release_readme(version, commit)
    checksums = "".join(
        f"{sha256_bytes(content)}  {path.relative_to(release_name).as_posix()}\n"
        for path, content in sorted(entries.items(), key=lambda item: item[0].as_posix())
    ).encode("utf-8")
    entries[PurePosixPath(release_name) / "SHA256SUMS"] = checksums
    manifest = {
        "schema_version": 1,
        "release_name": release_name,
        "version": version,
        "prepared_tag": f"v{version}",
        "tag_created": False,
        "source_commit": commit,
        "source_tree": git("rev-parse", f"{commit}^{{tree}}", root=root),
        "source_worktree_dirty": bool(dirty_status),
        # A source-commit timestamp, rather than wall-clock time, keeps archive
        # bytes reproducible when the tracked inputs are unchanged.
        "generated_at": release_timestamp,
        "availability": "sanitized research reproducibility bundle; repository visibility unchanged",
        "rights_boundary": (
            "TTLAB project authorization is not blanket third-party PDF redistribution permission. "
            "Recipients must supply separately authorized corpus files."
        ),
        "peer_review_remediation_v2": v2_validation,
        "included_file_count": len(entries) + 1,
        "excluded_tracked_files": excluded,
        "sanitization_event_count": total_redactions,
        "files": provenance,
        "mandatory_exclusions": [
            "all PDF files",
            "SQLite/runtime databases",
            "downloaded publications",
            "extracted and chunk text",
            "vector/keyword runtime indexes",
            "secrets and environment files",
            "private raw review prompts/inputs",
            "rights-sensitive remediation-v2 full raw outputs",
            "raw Europe PMC XML cache",
            "source-bearing interface screenshots",
        ],
        "verification": {
            "payload_sha256_file": "SHA256SUMS",
            "scan_patterns": sorted(SECRET_PATTERNS),
            "absolute_path_scan": True,
            "pdf_magic_scan": True,
        },
        "dependency_locks": {},
    }
    for lock_name, lock_path in {
        "python": "backend/requirements-lock.txt",
        "frontend": "frontend/package-lock.json",
    }.items():
        row = next((item for item in provenance if item["path"] == lock_path), None)
        manifest["dependency_locks"][lock_name] = {
            "path": lock_path,
            "source_sha256": row["source_sha256"] if row else None,
            "sha256": row["released_sha256"] if row else None,
        }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    entries[PurePosixPath(release_name) / "RELEASE_MANIFEST.json"] = manifest_bytes

    with tempfile.NamedTemporaryFile(prefix="ttlab-release-", suffix=".tar", delete=False) as handle:
        temporary_tar = Path(handle.name)
    try:
        with tarfile.open(temporary_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path, content in sorted(entries.items(), key=lambda item: item[0].as_posix()):
                info = tarfile.TarInfo(path.as_posix())
                info.size = len(content)
                info.mtime = commit_timestamp
                info.mode = 0o755 if path.suffix in {".sh", ".py"} and content.startswith(b"#!") else 0o644
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                archive.addfile(info, io.BytesIO(content))
        with temporary_tar.open("rb") as source, archive_path.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
                shutil.copyfileobj(source, compressed)
    finally:
        temporary_tar.unlink(missing_ok=True)

    archive_sha = sha256_path(archive_path)
    manifest["archive"] = {
        "path": archive_path.name,
        "bytes": archive_path.stat().st_size,
        "sha256": archive_sha,
    }
    manifest["archive_verification"] = verify_release(archive_path)
    manifest_copy_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    checksum_path.write_text(f"{archive_sha}  {archive_path.name}\n", encoding="utf-8")
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "release_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (evidence_dir / "release_archive.sha256").write_text(
            f"{archive_sha}  {archive_path.name}\n",
            encoding="utf-8",
        )
    return manifest


def verify_release(archive_path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    members = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        archive_members = archive.getmembers()
        if len(archive_members) > MAX_ARCHIVE_MEMBERS:
            raise RuntimeError(f"Release has too many archive members: {len(archive_members)}")
        total_declared_bytes = sum(member.size for member in archive_members if member.isfile())
        if total_declared_bytes > MAX_ARCHIVE_TOTAL_BYTES:
            raise RuntimeError(f"Release exceeds the uncompressed size limit: {total_declared_bytes}")
        names = [member.name for member in archive_members if member.isfile()]
        if len(names) != len(set(names)):
            raise RuntimeError("Release contains duplicate archive member names")
        manifest_names = [name for name in names if name.endswith("/RELEASE_MANIFEST.json")]
        checksum_names = [name for name in names if name.endswith("/SHA256SUMS")]
        if len(manifest_names) != 1:
            raise RuntimeError("Release has no RELEASE_MANIFEST.json")
        if len(checksum_names) != 1:
            raise RuntimeError("Release has no SHA256SUMS")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise RuntimeError("Release members do not share one archive root")
        release_root = next(iter(roots))
        payloads: dict[str, bytes] = {}
        for member in archive_members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) < 2
                or "\\" in member.name
                or "//" in member.name
                or member.name.startswith("./")
                or member.name != path.as_posix()
                or any(ord(character) < 32 for character in member.name)
            ):
                findings.append({"path": member.name, "finding": "unsafe_archive_path"})
                continue
            if not member.isfile():
                findings.append({"path": member.name, "finding": "unsupported_archive_member_type"})
                continue
            if member.size > MAX_ARCHIVE_FILE_BYTES:
                findings.append({"path": member.name, "finding": "archive_member_too_large"})
                continue
            members += 1
            extracted = archive.extractfile(member)
            content = extracted.read() if extracted else b""
            relative = path.relative_to(release_root).as_posix()
            payloads[relative] = content
            for finding in scan_payload(path, content):
                findings.append({"path": member.name, "finding": finding})
        checksum_content = payloads.get("SHA256SUMS", b"").decode("utf-8")
        checksum_entries: dict[str, str] = {}
        for line_number, line in enumerate(checksum_content.splitlines(), start=1):
            match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
            if not match:
                findings.append({"path": "SHA256SUMS", "finding": f"malformed_checksum_line:{line_number}"})
                continue
            digest, relative = match.groups()
            if relative in checksum_entries:
                findings.append({"path": relative, "finding": "duplicate_checksum_entry"})
                continue
            checksum_entries[relative] = digest
        expected_payloads = set(payloads) - {"SHA256SUMS", "RELEASE_MANIFEST.json"}
        if set(checksum_entries) != expected_payloads:
            missing = sorted(expected_payloads - set(checksum_entries))
            unexpected = sorted(set(checksum_entries) - expected_payloads)
            findings.append(
                {
                    "path": "SHA256SUMS",
                    "finding": f"checksum_inventory_mismatch:missing={missing[:5]}:unexpected={unexpected[:5]}",
                }
            )
        for relative, expected_digest in checksum_entries.items():
            content = payloads.get(relative)
            if content is not None and sha256_bytes(content) != expected_digest:
                findings.append({"path": relative, "finding": "checksum_mismatch"})
        findings.extend(_embedded_manifest_findings(payloads, release_root))
    if findings:
        raise RuntimeError(f"Release verification failed: {findings[:10]}")
    return {
        "status": "valid",
        "members": members,
        "checksum_entries_verified": len(checksum_entries),
        "archive_sha256": sha256_path(archive_path),
    }


def _embedded_manifest_findings(payloads: dict[str, bytes], release_root: str) -> list[dict[str, str]]:
    """Bind the embedded release attestation to the archive it describes."""

    findings: list[dict[str, str]] = []

    def reject(finding: str) -> None:
        findings.append({"path": "RELEASE_MANIFEST.json", "finding": f"embedded_manifest:{finding}"})

    try:
        manifest = json.loads(payloads.get("RELEASE_MANIFEST.json", b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("invalid_json")
        return findings
    if not isinstance(manifest, dict):
        reject("not_an_object")
        return findings
    if manifest.get("schema_version") != 1:
        reject("schema_version")
    if manifest.get("release_name") != release_root:
        reject("release_root_mismatch")
    version = manifest.get("version")
    source_commit = manifest.get("source_commit")
    source_tree = manifest.get("source_tree")
    if not isinstance(version, str) or not version:
        reject("invalid_version")
    elif manifest.get("prepared_tag") != f"v{version}":
        reject("prepared_tag_mismatch")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        reject("invalid_source_commit")
    if not isinstance(source_tree, str) or not re.fullmatch(r"[0-9a-f]{40}", source_tree):
        reject("invalid_source_tree")
    if not isinstance(manifest.get("source_worktree_dirty"), bool):
        reject("invalid_source_worktree_dirty")
    if not isinstance(manifest.get("tag_created"), bool):
        reject("invalid_tag_created")
    try:
        generated_at = datetime.fromisoformat(str(manifest.get("generated_at")))
        if generated_at.tzinfo is None:
            raise ValueError
    except ValueError:
        reject("invalid_generated_at")
    if isinstance(version, str) and isinstance(source_commit, str):
        expected_root = f"ttlab-research-advisor-{version}-{source_commit[:12]}"
        if release_root != expected_root:
            reject("release_name_provenance_mismatch")
    if manifest.get("included_file_count") != len(payloads):
        reject("included_file_count_mismatch")

    rows = manifest.get("files")
    if not isinstance(rows, list):
        reject("files_not_a_list")
        return findings
    described: set[str] = set()
    source_paths: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            reject(f"file_row_{index}_not_an_object")
            continue
        relative = row.get("path")
        source_path = row.get("source_path")
        if not isinstance(relative, str) or not relative:
            reject(f"file_row_{index}_invalid_path")
            continue
        relative_path = PurePosixPath(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.as_posix() != relative
            or "\\" in relative
            or "//" in relative
            or any(ord(character) < 32 for character in relative)
        ):
            reject(f"file_row_{index}_unsafe_path")
            continue
        if relative in described:
            reject(f"duplicate_file_path:{relative}")
        described.add(relative)
        if not isinstance(source_path, str) or not source_path:
            reject(f"file_row_{index}_invalid_source_path")
        elif PurePosixPath(source_path).as_posix() != source_path or PurePosixPath(source_path).is_absolute() or ".." in PurePosixPath(source_path).parts:
            reject(f"file_row_{index}_unsafe_source_path")
        elif source_path in source_paths:
            reject(f"duplicate_source_path:{source_path}")
        else:
            source_paths.add(source_path)
        content = payloads.get(relative)
        if content is None:
            reject(f"described_payload_missing:{relative}")
            continue
        if row.get("bytes") != len(content):
            reject(f"payload_size_mismatch:{relative}")
        if row.get("released_sha256") != sha256_bytes(content):
            reject(f"payload_hash_mismatch:{relative}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256", ""))):
            reject(f"invalid_source_hash:{relative}")
        redactions = row.get("sanitization_event_count")
        if not isinstance(redactions, int) or redactions < 0:
            reject(f"invalid_redaction_count:{relative}")

    generated = {"REPRODUCE.md", "SHA256SUMS", "RELEASE_MANIFEST.json"}
    expected_described = set(payloads) - generated
    if described != expected_described:
        missing = sorted(expected_described - described)
        unexpected = sorted(described - expected_described)
        reject(f"file_inventory_mismatch:missing={missing[:5]}:unexpected={unexpected[:5]}")
    redaction_total = sum(
        row.get("sanitization_event_count", 0)
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("sanitization_event_count"), int)
    )
    if manifest.get("sanitization_event_count") != redaction_total:
        reject("sanitization_event_count_mismatch")

    locks = manifest.get("dependency_locks")
    if not isinstance(locks, dict):
        reject("dependency_locks_missing")
    else:
        for name in ("python", "frontend"):
            lock = locks.get(name)
            if not isinstance(lock, dict):
                reject(f"dependency_lock_missing:{name}")
                continue
            lock_path = lock.get("path")
            expected_hash = lock.get("sha256")
            if lock_path not in payloads:
                reject(f"dependency_lock_payload_missing:{name}")
            elif expected_hash != sha256_bytes(payloads[lock_path]):
                reject(f"dependency_lock_hash_mismatch:{name}")
            described_row = next((row for row in rows if isinstance(row, dict) and row.get("path") == lock_path), None)
            if described_row is None or lock.get("source_sha256") != described_row.get("source_sha256"):
                reject(f"dependency_lock_source_hash_mismatch:{name}")
    v2_prefix = "artifacts/peer_review_remediation/v2/"
    v2_payload_names = {
        PurePosixPath(path).name for path in payloads if path.startswith(v2_prefix)
    }
    v2_validation = manifest.get("peer_review_remediation_v2")
    if not isinstance(v2_validation, dict):
        reject("peer_review_remediation_v2_validation_missing")
    elif v2_payload_names:
        if v2_payload_names != CANONICAL_V2_RELEASE_FILES:
            reject("peer_review_remediation_v2_inventory_mismatch")
        if (
            v2_validation.get("status") != "validated"
            or v2_validation.get("versionable_no_sensitive_text_claimed") is not True
            or v2_validation.get("package_file_count") != len(CANONICAL_V2_RELEASE_FILES)
        ):
            reject("peer_review_remediation_v2_validation_invalid")
    elif (
        v2_validation.get("status") != "not_present"
        or v2_validation.get("versionable_no_sensitive_text_claimed") is not False
    ):
        reject("peer_review_remediation_v2_absence_claim_invalid")
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify a sanitized, deterministic reproducibility archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--version", default=DEFAULT_VERSION)
    build.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    build.add_argument("--allow-dirty", action="store_true")
    build.add_argument("--evidence-dir", type=Path, default=None)
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "verify":
        print(json.dumps(verify_release(args.archive), indent=2))
        return
    manifest = build_release(
        output_root=args.out_dir,
        version=args.version,
        allow_dirty=args.allow_dirty,
        evidence_dir=args.evidence_dir,
    )
    print(json.dumps({"status": "valid", **manifest["archive"], "release_name": manifest["release_name"]}, indent=2))


if __name__ == "__main__":
    main()
