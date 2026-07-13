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
    "chunk_text",
    "context",
    "corrected_text",
    "page_text",
    "raw_prompt",
    "snippet",
    "source_excerpt",
    "source_text",
}
TEXT_PATH_MARKERS = {"adjudicated_claims", "citations", "claims", "pages", "retrieved_chunks", "source_records", "supporting_sources"}
LOCAL_PATH_PATTERN = re.compile(r"(?:/mnt/[a-z]/|/home/[^/]+/|[A-Za-z]:\\Users\\)")
SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer_token": re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{16,}"),
}


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
    if parts[:2] == ("artifacts", "baseline"):
        return False, "local_baseline_environment"
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
            if isinstance(item, str) and (
                lowered in TEXT_BEARING_KEYS
                or (lowered == "text" and bool(TEXT_PATH_MARKERS.intersection(path)))
            ):
                sanitized[key] = redaction(item, "source_or_answer_text_not_redistributed")
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
figure sources, and reproduction instructions. Run `make reproduce-quick` for
the dependency and artifact gates, or `make reproduce` with separately
authorized local corpus inputs for the full pipeline.

The bundle intentionally excludes all PDFs, SQLite databases, extracted/chunk
text, vector indexes, secrets, `.env` files, private AI-review prompts, and raw
Europe PMC XML. TTLAB project authorization does not establish permission to
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
    release_name = f"ttlab-research-advisor-{version}-{short_commit}"
    output_root.mkdir(parents=True, exist_ok=True)
    archive_path = output_root / f"{release_name}.tar.gz"
    manifest_copy_path = output_root / f"{release_name}.manifest.json"
    checksum_path = output_root / f"{release_name}.sha256"
    excluded: list[dict[str, str]] = []
    entries: dict[PurePosixPath, bytes] = {}
    provenance: list[dict[str, Any]] = []
    total_redactions = 0

    for relative in sorted(tracked_paths(root), key=lambda value: value.as_posix()):
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
        if relative.parts[:2] == ("data", "seed") and relative.suffix == ".json":
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
        "source_worktree_dirty": bool(dirty_status),
        # A source-commit timestamp, rather than wall-clock time, keeps archive
        # bytes reproducible when the tracked inputs are unchanged.
        "generated_at": release_timestamp,
        "availability": "sanitized research reproducibility bundle; repository visibility unchanged",
        "rights_boundary": (
            "TTLAB project authorization is not blanket third-party PDF redistribution permission. "
            "Recipients must supply separately authorized corpus files."
        ),
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
            "raw Europe PMC XML cache",
        ],
        "verification": {
            "payload_sha256_file": "SHA256SUMS",
            "scan_patterns": sorted(SECRET_PATTERNS),
            "absolute_path_scan": True,
            "pdf_magic_scan": True,
        },
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
    verify_release(archive_path)
    return manifest


def verify_release(archive_path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    members = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        archive_members = archive.getmembers()
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
            if path.is_absolute() or ".." in path.parts:
                findings.append({"path": member.name, "finding": "unsafe_archive_path"})
                continue
            if not member.isfile():
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
    if findings:
        raise RuntimeError(f"Release verification failed: {findings[:10]}")
    return {
        "status": "valid",
        "members": members,
        "checksum_entries_verified": len(checksum_entries),
        "archive_sha256": sha256_path(archive_path),
    }


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
