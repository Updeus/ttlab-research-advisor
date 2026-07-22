from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_section_quality_silver_v1",
    ROOT / "data" / "evaluation" / "validate_section_quality_silver_v1.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE paper (paper_id TEXT PRIMARY KEY, extracted_json_path TEXT NOT NULL);
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            source_hash TEXT NOT NULL,
            section TEXT NOT NULL
        );
        INSERT INTO paper VALUES ('paper-1', 'data/extracted_text/paper-1.json');
        """
    )
    return connection


def case() -> dict:
    return {
        "case_id": "section-silver-test",
        "paper_id": "paper-1",
        "chunk_id": "paper-1-chunk-old",
        "chunk_index": 0,
        "page_start": 1,
        "page_end": 2,
    }


def test_current_evaluation_resolves_unique_stable_locator_after_chunk_hash_drift() -> None:
    connection = database()
    connection.execute(
        "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("paper-1-chunk-new", "paper-1", 0, 1, 2, "new-hash", "Introduction"),
    )

    row, resolution = VALIDATOR.resolve_case_chunk(
        connection,
        case(),
        evaluate_current=True,
    )

    assert resolution == "stable_paper_chunk_page_locator"
    assert row["chunk_id"] == "paper-1-chunk-new"


def test_frozen_validation_rejects_missing_exact_chunk_id() -> None:
    connection = database()
    connection.execute(
        "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("paper-1-chunk-new", "paper-1", 0, 1, 2, "new-hash", "Introduction"),
    )

    with pytest.raises(AssertionError, match="frozen chunk_id is absent"):
        VALIDATOR.resolve_case_chunk(connection, case(), evaluate_current=False)


def test_current_evaluation_rejects_ambiguous_stable_locator() -> None:
    connection = database()
    connection.executemany(
        "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("paper-1-chunk-new-a", "paper-1", 0, 1, 2, "new-hash-a", "Introduction"),
            ("paper-1-chunk-new-b", "paper-1", 0, 1, 2, "new-hash-b", "Introduction"),
        ],
    )

    with pytest.raises(AssertionError, match="matched 2 rows"):
        VALIDATOR.resolve_case_chunk(connection, case(), evaluate_current=True)
