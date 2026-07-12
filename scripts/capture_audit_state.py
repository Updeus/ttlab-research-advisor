#!/usr/bin/env python3
"""Capture path-independent environment and repository/corpus inventory JSON.

The script intentionally records metadata, counts, statuses, and hashes only.
It never copies database rows containing questions, student profiles, generated
answers, or document text into the committed audit artefacts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_DB = DATA / "papers.db"


def run(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if executable is None:
        return {"available": False, "command": command, "output": None}
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = (completed.stdout or completed.stderr).strip()
    return {
        "available": True,
        "command": command,
        "exit_code": completed.returncode,
        "output": output,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def file_group(relative_directory: str, patterns: tuple[str, ...]) -> list[dict[str, Any]]:
    base = ROOT / relative_directory
    if not base.exists():
        return []
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(path for path in base.rglob(pattern) if path.is_file() and path.name != ".gitkeep")
    return [file_record(path) for path in sorted(paths)]


def sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def scalar(connection: sqlite3.Connection, sql: str) -> int:
    value = connection.execute(sql).fetchone()[0]
    return int(value or 0)


def distribution(connection: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    rows = connection.execute(
        f'SELECT COALESCE(CAST("{column}" AS TEXT), "<null>"), COUNT(*) '
        f'FROM "{table}" GROUP BY "{column}" ORDER BY 1'
    ).fetchall()
    return {str(label): int(count) for label, count in rows}


def database_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": path.relative_to(ROOT).as_posix()}
    connection = sqlite3.connect(path)
    try:
        tables = sqlite_tables(connection)
        count_tables = (
            "paper",
            "author",
            "chunk",
            "topic",
            "papertopic",
            "authortopic",
            "paperartifact",
            "raganswer",
            "thesisrecommendation",
            "reviewevent",
            "chunk_fts",
        )
        counts = {
            table: scalar(connection, f'SELECT COUNT(*) FROM "{table}"')
            for table in count_tables
            if table in tables
        }
        paper_columns = {
            row[1] for row in connection.execute('PRAGMA table_info("paper")').fetchall()
        } if "paper" in tables else set()
        pages = {
            "declared_page_total": scalar(connection, "SELECT SUM(page_count) FROM paper")
            if "page_count" in paper_columns
            else None,
            "papers_with_page_count": scalar(connection, "SELECT COUNT(*) FROM paper WHERE page_count IS NOT NULL")
            if "page_count" in paper_columns
            else None,
            "chunk_page_max_total": scalar(
                connection,
                "SELECT SUM(max_page) FROM (SELECT paper_id, MAX(page_end) AS max_page FROM chunk GROUP BY paper_id)",
            )
            if "chunk" in tables
            else None,
        }
        status_specs = {
            "paper": ("ingestion_status", "pdf_text_status", "review_status"),
            "chunk": ("embedding_status", "section"),
            "author": ("review_status",),
            "topic": ("review_status", "source"),
            "paperartifact": ("generation_status", "grounding_status", "review_status"),
            "raganswer": ("grounding_status", "review_status", "retrieval_mode", "provider", "model"),
            "thesisrecommendation": ("grounding_status", "review_status", "retrieval_mode", "provider", "model"),
            "reviewevent": ("item_type", "action", "new_status", "reviewer_name"),
        }
        statuses: dict[str, dict[str, dict[str, int]]] = {}
        for table, columns in status_specs.items():
            if table not in tables:
                continue
            available_columns = {
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            statuses[table] = {
                column: distribution(connection, table, column)
                for column in columns
                if column in available_columns
            }
        return {
            "available": True,
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "sqlite_integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "counts": counts,
            "pages": pages,
            "statuses": statuses,
        }
    finally:
        connection.close()


def git_environment() -> dict[str, Any]:
    status = run(["git", "status", "--short"])
    status_lines = status.get("output", "").splitlines() if status.get("output") else []
    remotes = run(["git", "remote", "-v"])
    return {
        "head": run(["git", "rev-parse", "HEAD"]),
        "origin_main": run(["git", "rev-parse", "origin/main"]),
        "branch": run(["git", "branch", "--show-current"]),
        "status_short": status_lines,
        "dirty": bool(status_lines),
        "remotes": remotes.get("output", "").splitlines() if remotes.get("output") else [],
    }


def cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return platform.processor() or None
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or None


def memory_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return None


def package_versions() -> dict[str, str | None]:
    requirement_names: set[str] = set()
    requirements = ROOT / "backend" / "requirements.txt"
    if requirements.exists():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                name = stripped.split("==", 1)[0].split("[", 1)[0].strip()
                if name:
                    requirement_names.add(name)
    requirement_names.update({"pytest", "pip", "setuptools"})
    versions: dict[str, str | None] = {}
    for name in sorted(requirement_names, key=str.lower):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(canonical, encoding="utf-8")


def create_private_backup(output_dir: Path, database: Path) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = output_dir / "private-backups" / timestamp
    candidates = [database]
    index_dir = DATA / "indexes"
    if index_dir.exists():
        candidates.extend(sorted(path for path in index_dir.rglob("*") if path.is_file() and path.name != ".gitkeep"))
    records: list[dict[str, Any]] = []
    for source in candidates:
        if not source.exists():
            continue
        relative_source = source.relative_to(ROOT)
        destination = backup_root / relative_source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        source_hash = sha256(source)
        destination_hash = sha256(destination)
        if source_hash != destination_hash:
            raise RuntimeError(f"Backup checksum mismatch for {relative_source}")
        records.append(
            {
                "source": relative_source.as_posix(),
                "private_backup": destination.relative_to(ROOT).as_posix(),
                "bytes": source.stat().st_size,
                "sha256": source_hash,
                "verified": True,
            }
        )
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "private_backup_root": backup_root.relative_to(ROOT).as_posix(),
        "gitignored": True,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "baseline")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup", action="store_true", help="copy database/indexes to the gitignored private backup area")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    database = args.database if args.database.is_absolute() else ROOT / args.database

    tools = {
        name: run(command)
        for name, command in {
            "python": [sys.executable, "--version"],
            "pip": [sys.executable, "-m", "pip", "--version"],
            "git": ["git", "--version"],
            "node": ["node", "--version"],
            "npm": ["npm", "--version"],
            "sqlite": ["sqlite3", "--version"],
            "tectonic": ["tectonic", "--version"],
            "latexmk": ["latexmk", "--version"],
            "chktex": ["chktex", "--version"],
            "qpdf": ["qpdf", "--version"],
            "pdfinfo": ["pdfinfo", "-v"],
            "pdftotext": ["pdftotext", "-v"],
            "pdffonts": ["pdffonts", "-v"],
            "nvidia_smi": ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
        }.items()
    }
    environment = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": os.environ.get("TZ") or datetime.now().astimezone().tzname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "cpu_model": cpu_model(),
            "logical_cpu_count": os.cpu_count(),
            "memory_bytes": memory_bytes(),
        },
        "git": git_environment(),
        "tools": tools,
        "python_packages": package_versions(),
        "frontend_package_json": file_record(ROOT / "frontend" / "package.json"),
        "frontend_lock": file_record(ROOT / "frontend" / "package-lock.json"),
    }

    groups = {
        "pdfs": file_group("data/pdfs", ("*.pdf",)),
        "extracted_text": file_group("data/extracted_text", ("*.json", "*.txt")),
        "chunks": file_group("data/chunks", ("*.json",)),
        "indexes": file_group("data/indexes", ("*",)),
        "generated": file_group("data/generated", ("*.json", "*.jsonl", "*.csv")),
        "evaluation": file_group("data/evaluation", ("*.json", "*.jsonl", "*.csv")),
        "seed": file_group("data/seed", ("*.json", "*.jsonl", "*.csv")),
    }
    manifest = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": environment["git"],
        "database": database_inventory(database),
        "file_counts": {name: len(records) for name, records in groups.items()},
        "files": groups,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest["manifest_sha256"] = manifest_hash

    write_json(output_dir / "environment.json", environment)
    write_json(output_dir / "pre-change-manifest.json", manifest)
    if args.backup:
        write_json(output_dir / "backup-manifest.json", create_private_backup(output_dir, database))
    print(json.dumps({"output_dir": output_dir.relative_to(ROOT).as_posix(), "manifest_sha256": manifest_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
