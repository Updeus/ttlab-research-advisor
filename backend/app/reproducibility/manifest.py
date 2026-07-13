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


def manifest(root: Path, work: Path, mode: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    excluded_runtime_payloads = 0
    for path in sorted(work.rglob("*")):
        if not path.is_file() or path.name == "reproduction_manifest.json":
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
    return {
        "schema_version": 1,
        "status": "completed",
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": git(root, "rev-parse", "HEAD"),
        "source_worktree_dirty": bool(git(root, "status", "--porcelain")),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
        },
        "work_directory": str(work),
        "file_count": len(files),
        "restricted_runtime_payload_count": excluded_runtime_payloads,
        "files": files,
        "claim_boundary": (
            "This manifest proves command/artifact execution in the recorded local environment. "
            "It is not evidence of redistribution rights or external generalizability."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash a completed reproduction workspace.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--mode", choices=["quick", "full"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    value = manifest(args.root.resolve(), args.work.resolve(), args.mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "files": value["file_count"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
