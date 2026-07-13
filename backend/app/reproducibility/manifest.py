from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def command_version(root: Path, *command: str) -> str | None:
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    output = (result.stdout or result.stderr).splitlines()
    return output[0].strip() if output else None


def manifest(
    root: Path,
    work: Path,
    mode: str,
    *,
    source_commit: str | None = None,
    source_tree: str | None = None,
    source_clean_at_start: bool | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    excluded_runtime_payloads = 0
    excluded_runtime_directories: list[str] = []
    candidates: list[Path] = []
    excluded_directory_names = {".git", ".pytest_cache", ".venv", "__pycache__", "node_modules"}
    for directory, directory_names, file_names in os.walk(work, followlinks=False):
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = directory_path / name
            if name in excluded_directory_names or candidate.is_symlink():
                excluded_runtime_directories.append(candidate.relative_to(work).as_posix())
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories
        candidates.extend(directory_path / name for name in sorted(file_names))
    for path in sorted(candidates):
        if path.name in {"reproduction_manifest.json", "REPRODUCTION_SHA256SUMS"}:
            continue
        relative = path.relative_to(work)
        is_restricted_runtime = bool(
            {"pdfs", "extracted_text", "chunks", "indexes"}.intersection(relative.parts)
            or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pdf"}
        )
        if is_restricted_runtime:
            excluded_runtime_payloads += 1
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_path(path),
                "restricted_runtime_payload": is_restricted_runtime,
            }
        )
    post_status = git(root, "status", "--porcelain", "--untracked-files=all").splitlines()
    resolved_commit = source_commit or git(root, "rev-parse", "HEAD")
    resolved_tree = source_tree or git(root, "rev-parse", f"{resolved_commit}^{{tree}}")
    clean_at_start = source_clean_at_start if source_clean_at_start is not None else not post_status
    return {
        "schema_version": 2,
        "status": "completed",
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": resolved_commit,
        "source_snapshot": {
            "commit": resolved_commit,
            "tree": resolved_tree,
            "construction": "detached_git_worktree" if source_commit is not None else "current_worktree",
            "clean_before_execution": clean_at_start,
        },
        "post_execution_worktree": {
            "dirty": bool(post_status),
            "changed_path_count": len(post_status),
            "changed_paths": post_status,
            "interpretation": (
                "Generated outputs may make the disposable worktree dirty after execution; this does not alter the "
                "recorded clean source snapshot commit/tree."
            ),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "node": command_version(root, "node", "--version"),
            "npm": command_version(root, "npm", "--version"),
            "git": command_version(root, "git", "--version"),
            "dependency_locks": {
                "python": {
                    "path": "backend/requirements-lock.txt",
                    "sha256": sha256_path(root / "backend/requirements-lock.txt"),
                },
                "frontend": {
                    "path": "frontend/package-lock.json",
                    "sha256": sha256_path(root / "frontend/package-lock.json"),
                },
            },
        },
        "work_directory": ".",
        "file_count": len(files),
        "restricted_runtime_payload_count": excluded_runtime_payloads,
        "excluded_runtime_directories": excluded_runtime_directories,
        "files": files,
        "claim_boundary": (
            "This manifest proves command/artifact execution in the recorded local environment. "
            "It is not evidence of redistribution rights or external generalizability."
        ),
    }


def write_manifest_and_checksums(value: dict[str, Any], output: Path, work: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checksum_path = output.parent / "REPRODUCTION_SHA256SUMS"
    entries = [
        f"{row['sha256']}  {row['path']}"
        for row in value["files"]
    ]
    entries.append(f"{sha256_path(output)}  {output.relative_to(work).as_posix()}")
    checksum_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return checksum_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash a completed reproduction workspace.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--mode", choices=["quick", "full"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--source-tree")
    parser.add_argument("--source-clean-at-start", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    value = manifest(
        args.root.resolve(),
        args.work.resolve(),
        args.mode,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        source_clean_at_start=True if args.source_clean_at_start else None,
    )
    checksum_path = write_manifest_and_checksums(value, args.out, args.work.resolve())
    print(
        json.dumps(
            {
                "status": value["status"],
                "files": value["file_count"],
                "out": str(args.out),
                "checksums": str(checksum_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
