from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CORE_TABLES = (
    "paper",
    "author",
    "authoralias",
    "topic",
    "papertopic",
    "authortopic",
    "chunk",
    "raganswer",
    "thesisrecommendation",
    "paperartifact",
    "reviewevent",
)
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class SourceDatabaseChangedError(RuntimeError):
    """Raised when the source database changes while its snapshot is built."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _immutable_read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro&immutable=1"


def _journal_mode(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA journal_mode").fetchone()
    return str(row[0]).lower() if row else "unknown"


def _integrity_check(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]


def _core_table_counts(connection: sqlite3.Connection) -> tuple[dict[str, int | None], list[str]]:
    available = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    counts: dict[str, int | None] = {}
    missing: list[str] = []
    for table in CORE_TABLES:
        if table not in available:
            counts[table] = None
            missing.append(table)
            continue
        # Table names come only from the fixed CORE_TABLES tuple above.
        counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    return counts, missing


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sqlite_sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)


def _checkpoint_and_remove_snapshot_sidecars(path: Path) -> None:
    """Checkpoint a copied WAL database and remove temp-name sidecars."""

    with sqlite3.connect(path, timeout=30.0) as connection:
        if _journal_mode(connection) == "wal":
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if not checkpoint or int(checkpoint[0]) != 0:
                raise RuntimeError("Snapshot WAL checkpoint did not complete")
    wal_path = Path(f"{path}-wal")
    if wal_path.exists() and wal_path.stat().st_size != 0:
        raise RuntimeError("Snapshot WAL remained non-empty after checkpoint")
    for sidecar in _sqlite_sidecars(path):
        sidecar.unlink(missing_ok=True)


def _publish_without_overwrite(temporary: Path, target: Path) -> None:
    """Publish a same-directory temporary file without a clobber race."""

    try:
        os.link(temporary, target)
    except FileExistsError as exc:
        raise FileExistsError(f"Refusing to overwrite existing snapshot target: {target.name}") from exc
    temporary.unlink()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def snapshot_database(source: Path, target: Path, evidence: Path) -> dict[str, Any]:
    source = source.resolve()
    target = target.resolve()
    evidence = evidence.resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Source database is not a file: {source.name}")
    if source == target:
        raise ValueError("Source and snapshot target must be different files")
    if evidence in {source, target}:
        raise ValueError("Evidence path must differ from the source and snapshot target")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing snapshot target: {target.name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)

    source_sha256_before = sha256_path(source)
    source_bytes_before = source.stat().st_size
    source_journal_mode_before = "unknown"
    source_journal_mode_after = "unknown"
    source_data_version_before: int | None = None
    source_data_version_after: int | None = None

    try:
        with sqlite3.connect(_read_only_uri(source), uri=True, timeout=30.0) as source_connection:
            source_connection.execute("PRAGMA query_only=ON")
            source_connection.execute("PRAGMA busy_timeout=30000")
            source_journal_mode_before = _journal_mode(source_connection)
            source_data_version_before = int(source_connection.execute("PRAGMA data_version").fetchone()[0])

            with sqlite3.connect(temporary, timeout=30.0) as target_connection:
                source_connection.backup(target_connection)

            _checkpoint_and_remove_snapshot_sidecars(temporary)

            source_sha256_after = sha256_path(source)
            source_bytes_after = source.stat().st_size
            source_journal_mode_after = _journal_mode(source_connection)
            source_data_version_after = int(source_connection.execute("PRAGMA data_version").fetchone()[0])

        source_drift = (
            source_sha256_before != source_sha256_after
            or source_bytes_before != source_bytes_after
            or source_journal_mode_before != source_journal_mode_after
            or source_data_version_before != source_data_version_after
        )
        if source_drift:
            raise SourceDatabaseChangedError(
                "Source database changed while the SQLite backup was running; snapshot was not published"
            )

        with sqlite3.connect(_immutable_read_only_uri(temporary), uri=True, timeout=30.0) as snapshot_connection:
            integrity_rows = _integrity_check(snapshot_connection)
            if integrity_rows != ["ok"]:
                raise RuntimeError(f"Snapshot integrity_check failed: {integrity_rows[:5]}")
            snapshot_journal_mode = _journal_mode(snapshot_connection)
            table_row_counts, missing_core_tables = _core_table_counts(snapshot_connection)

        _fsync_file(temporary)
        snapshot_sha256 = sha256_path(temporary)
        snapshot_bytes = temporary.stat().st_size
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "valid",
            "method": "sqlite3.Connection.backup",
            "generated_at": datetime.now(UTC).isoformat(),
            "source": {
                "label": source.name,
                "sha256_before": source_sha256_before,
                "sha256_after": source_sha256_after,
                "bytes_before": source_bytes_before,
                "bytes_after": source_bytes_after,
                "journal_mode_before": source_journal_mode_before,
                "journal_mode_after": source_journal_mode_after,
                "data_version_before": source_data_version_before,
                "data_version_after": source_data_version_after,
            },
            "snapshot": {
                "label": target.name,
                "sha256": snapshot_sha256,
                "bytes": snapshot_bytes,
                "journal_mode": snapshot_journal_mode,
                "integrity_check": "ok",
            },
            "table_row_counts": table_row_counts,
            "missing_core_tables": missing_core_tables,
            "claim_boundary": (
                "The record proves an integrity-checked SQLite backup of one source state. "
                "It does not establish redistribution rights for the database or its source documents."
            ),
        }

        _publish_without_overwrite(temporary, target)
        try:
            atomic_write_json(evidence, result)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return result
    finally:
        temporary.unlink(missing_ok=True)
        for sidecar in _sqlite_sidecars(temporary):
            sidecar.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an integrity-checked, no-clobber SQLite snapshot.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = snapshot_database(args.source, args.target, args.evidence)
    print(
        json.dumps(
            {
                "status": result["status"],
                "source": result["source"]["label"],
                "snapshot": result["snapshot"]["label"],
                "snapshot_sha256": result["snapshot"]["sha256"],
                "evidence": args.evidence.name,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
