from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from app.evaluation import topic_author_eval


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_topic_author_silver_v1",
    ROOT / "data" / "evaluation" / "validate_topic_author_silver_v1.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            section TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            text TEXT NOT NULL
        );
        """
    )
    return connection


def evidence() -> dict:
    text = "Stable opening source passage for the reviewed label."
    return {
        "evidence_type": "source_chunk",
        "chunk_id": "paper-1-chunk-0001-aaaaaaaaaaaa",
        "source_hash": "a" * 64,
        "page_start": 1,
        "page_end": 2,
        "section": "Introduction",
        "text": text,
    }


def insert_chunk(
    connection: sqlite3.Connection,
    chunk_id: str,
    *,
    text: str = "Stable opening source passage for the reviewed label.",
) -> None:
    connection.execute(
        "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (chunk_id, "paper-1", 1, 1, 2, "Introduction", "b" * 64, text),
    )


def test_unique_current_locator_rebind_requires_exact_persisted_excerpt() -> None:
    connection = database()
    current_id = "paper-1-chunk-0001-bbbbbbbbbbbb"
    insert_chunk(connection, current_id)

    result = VALIDATOR.resolve_source_chunk(
        connection,
        case_id="topic-silver-test",
        paper_id="paper-1",
        evidence=evidence(),
        current_dense_chunk_ids={current_id},
    )

    assert result["resolution"] == "stable_paper_chunk_page_section_locator"
    assert result["frozen_chunk_id"] == "paper-1-chunk-0001-aaaaaaaaaaaa"
    assert result["current_chunk_id"] == current_id
    assert result["persisted_excerpt_sha256"] == result["current_excerpt_sha256"]


def test_unique_current_locator_rejects_excerpt_drift() -> None:
    connection = database()
    current_id = "paper-1-chunk-0001-bbbbbbbbbbbb"
    insert_chunk(connection, current_id, text="A different source passage.")

    with pytest.raises(ValueError, match="persisted source excerpt differs"):
        VALIDATOR.resolve_source_chunk(
            connection,
            case_id="topic-silver-test",
            paper_id="paper-1",
            evidence=evidence(),
            current_dense_chunk_ids={current_id},
        )


def test_current_locator_rejects_ambiguous_rows() -> None:
    connection = database()
    first = "paper-1-chunk-0001-bbbbbbbbbbbb"
    second = "paper-1-chunk-0001-cccccccccccc"
    insert_chunk(connection, first)
    insert_chunk(connection, second)

    with pytest.raises(ValueError, match="matched 2 rows"):
        VALIDATOR.resolve_source_chunk(
            connection,
            case_id="topic-silver-test",
            paper_id="paper-1",
            evidence=evidence(),
            current_dense_chunk_ids={first, second},
        )


def receipt() -> dict:
    return {
        "current_case_binding": {
            "case_bindings": [
                {
                    "case_id": "topic-silver-test",
                    "paper_id": "paper-1",
                    "resolution": "stable_paper_chunk_page_section_locator",
                    "frozen_chunk_id": "paper-1-chunk-0001-aaaaaaaaaaaa",
                    "current_chunk_id": "paper-1-chunk-0001-bbbbbbbbbbbb",
                    "frozen_source_hash": "a" * 64,
                    "current_source_hash": "b" * 64,
                    "persisted_excerpt_exact_match": True,
                }
            ],
        },
    }


def cases() -> list[dict]:
    return [
        {
            "case_id": "topic-silver-test",
            "paper_id": "paper-1",
            "evidence": [evidence()],
            "label_evidence": {"networks": ["paper-1-chunk-0001-aaaaaaaaaaaa"]},
        }
    ]


def test_evaluator_consumes_only_a_live_validator_matching_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(receipt()), encoding="utf-8")
    monkeypatch.setattr(
        topic_author_eval,
        "validate_topic_silver_binding",
        lambda output_json=None: receipt(),
    )

    rebound, recorded = topic_author_eval.consume_current_binding_receipt(cases(), path)

    source = rebound[0]["evidence"][0]
    assert recorded == receipt()
    assert source["frozen_chunk_id"] == "paper-1-chunk-0001-aaaaaaaaaaaa"
    assert source["chunk_id"] == "paper-1-chunk-0001-bbbbbbbbbbbb"
    assert rebound[0]["label_evidence"]["networks"] == ["paper-1-chunk-0001-bbbbbbbbbbbb"]


def test_evaluator_rejects_stale_binding_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "binding.json"
    stale = receipt()
    stale["current_case_binding"]["case_bindings"][0]["current_chunk_id"] = (
        "paper-1-chunk-0001-cccccccccccc"
    )
    path.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(
        topic_author_eval,
        "validate_topic_silver_binding",
        lambda output_json=None: receipt(),
    )

    with pytest.raises(RuntimeError, match="stale"):
        topic_author_eval.consume_current_binding_receipt(cases(), path)


def test_external_binding_receipt_path_is_recordable(tmp_path: Path) -> None:
    path = tmp_path / "binding.json"

    assert topic_author_eval.display_path(path) == str(path.resolve())
