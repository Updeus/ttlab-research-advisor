from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.reproducibility import database_snapshot


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE paper (paper_id TEXT PRIMARY KEY, title TEXT NOT NULL);
            CREATE TABLE chunk (chunk_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, text TEXT NOT NULL);
            INSERT INTO paper VALUES ('p1', 'First paper'), ('p2', 'Second paper');
            INSERT INTO chunk VALUES ('c1', 'p1', 'source passage');
            """
        )


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_snapshot_uses_backup_records_integrity_and_avoids_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "authorized.db"
    target = tmp_path / "frozen.db"
    evidence = tmp_path / "snapshot.json"
    _database(source)

    result = database_snapshot.snapshot_database(source, target, evidence)

    assert target.is_file()
    assert evidence.is_file()
    assert json.loads(evidence.read_text(encoding="utf-8")) == result
    assert result["status"] == "valid"
    assert result["method"] == "sqlite3.Connection.backup"
    assert result["source"]["label"] == "authorized.db"
    assert result["source"]["sha256_before"] == result["source"]["sha256_after"]
    assert result["source"]["bytes_before"] == result["source"]["bytes_after"]
    assert result["snapshot"]["label"] == "frozen.db"
    assert result["snapshot"]["sha256"] == database_snapshot.sha256_path(target)
    assert result["snapshot"]["bytes"] == target.stat().st_size
    assert result["snapshot"]["integrity_check"] == "ok"
    assert result["table_row_counts"]["paper"] == 2
    assert result["table_row_counts"]["chunk"] == 1
    assert "author" in result["missing_core_tables"]
    assert all(str(tmp_path) not in value for value in _strings(result))

    with sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 2


def test_snapshot_never_overwrites_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "authorized.db"
    target = tmp_path / "frozen.db"
    evidence = tmp_path / "snapshot.json"
    _database(source)
    target.write_bytes(b"do-not-overwrite")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        database_snapshot.snapshot_database(source, target, evidence)

    assert target.read_bytes() == b"do-not-overwrite"
    assert not evidence.exists()


def test_snapshot_rejects_source_hash_drift_without_publishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "authorized.db"
    target = tmp_path / "frozen.db"
    evidence = tmp_path / "snapshot.json"
    _database(source)
    observed = database_snapshot.sha256_path(source)
    hashes = iter((observed, "f" * 64))
    monkeypatch.setattr(database_snapshot, "sha256_path", lambda _path: next(hashes))

    with pytest.raises(database_snapshot.SourceDatabaseChangedError, match="changed"):
        database_snapshot.snapshot_database(source, target, evidence)

    assert not target.exists()
    assert not evidence.exists()
    assert list(tmp_path.glob(".frozen.db.*.tmp")) == []


def test_snapshot_rejects_failed_integrity_check_without_publishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "authorized.db"
    target = tmp_path / "frozen.db"
    evidence = tmp_path / "snapshot.json"
    _database(source)
    monkeypatch.setattr(database_snapshot, "_integrity_check", lambda _connection: ["malformed database"])

    with pytest.raises(RuntimeError, match="integrity_check failed"):
        database_snapshot.snapshot_database(source, target, evidence)

    assert not target.exists()
    assert not evidence.exists()
