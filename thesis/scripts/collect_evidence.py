#!/usr/bin/env python3
"""Generate a compact, path-independent thesis evidence snapshot.

Frozen experiment artefacts are authoritative for empirical metrics.  The live
SQLite database is read only for operational counts/integrity after migrations
and generated-output review.  No restricted paper text is copied to output.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from app.evaluation.performance_validator import (
    FULL_REQUIRED_STAGES,
    validate_performance_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "thesis" / "generated"
DB = ROOT / "data" / "papers.db"
SOURCES = {
    "phase1": ROOT / "artifacts/phase1/phase1_evidence.json",
    "retrieval": ROOT / "artifacts/phase2/retrieval/summary.json",
    "retrieval_statistics": ROOT / "artifacts/phase2/retrieval/paired_statistics.json",
    "qa": ROOT / "artifacts/phase3/qa/qa_faithfulness_metrics_v1.json",
    "qa_manifest": ROOT / "artifacts/phase3/qa/qa_faithfulness_manifest_v1.json",
    "recommendation": ROOT / "artifacts/phase4/recommendation_proxy_v1/aggregate_results.json",
    "topics": ROOT / "artifacts/phase4/topic_author/topic_metrics.json",
    "authors": ROOT / "artifacts/phase4/topic_author/author_identity_audit.json",
    "generated_review": ROOT / "artifacts/phase4/generated_output_review/generated_output_review_summary.json",
    "generated_review_idempotence": ROOT / "artifacts/phase4/generated_output_review/idempotence_evidence.json",
    "external_sanity": ROOT / "artifacts/phase6/external_sanity/external_sanity_manifest.json",
    "performance": ROOT / "artifacts/phase6/performance/performance_full_results.json",
    "performance_validation": ROOT / "artifacts/phase6/performance/performance_validation.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_provenance() -> dict[str, Any]:
    backend_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "backend"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if backend_status:
        raise RuntimeError("Backend source must be clean before thesis evidence generation")

    def git_value(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    script = Path(__file__).resolve()
    return {
        "committed_base": {
            "commit": git_value("rev-parse", "HEAD"),
            "tree": git_value("rev-parse", "HEAD^{tree}"),
            "backend_dirty": False,
        },
        "exact_generator": {
            "path": script.relative_to(ROOT).as_posix(),
            "sha256": sha256(script),
        },
        "expected_manuscript_output_dirty_boundary": [
            "thesis/generated/**",
            "build/thesis.pdf",
        ],
        "semantics": (
            "The commit/tree identify the clean committed application base. The exact live generator and "
            "all empirical inputs are SHA-256 bound in this snapshot/manuscript manifest. Generated thesis "
            "outputs are expected to differ from the committed base and are not described as a final clean commit."
        ),
    }


def load(name: str) -> dict[str, Any] | None:
    path = SOURCES[name]
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
    )


def grouped(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def database_snapshot() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not DB.is_file():
        return ({"available": False, "path": "data/papers.db"}, [], [], [])
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        tables = [
            "paper", "author", "authoralias", "chunk", "raganswer", "thesisrecommendation",
            "paperartifact", "topic", "papertopic", "authortopic", "reviewevent",
        ]
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
            if table_exists(connection, table)
        }
        totals = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(page_count),0), COALESCE(SUM(total_word_count),0), "
            "COALESCE(SUM(total_char_count),0) FROM paper WHERE pdf_text_status='extracted'"
        ).fetchone()
        status_tables: dict[str, list[dict[str, Any]]] = {}
        for table in ("raganswer", "thesisrecommendation", "paperartifact"):
            if table_exists(connection, table):
                status_tables[table] = grouped(
                    connection,
                    f'SELECT review_status, COUNT(*) AS count FROM "{table}" GROUP BY review_status ORDER BY review_status',
                )
        years = grouped(
            connection,
            "SELECT COALESCE(CAST(year AS TEXT),'Unknown') AS year, COUNT(*) AS count "
            "FROM paper GROUP BY year ORDER BY CASE WHEN year IS NULL THEN 1 ELSE 0 END, year",
        )
        paper_status = grouped(
            connection,
            "SELECT corpus_eligibility_status AS status, COUNT(*) AS count FROM paper "
            "GROUP BY corpus_eligibility_status ORDER BY status",
        )
        top_topics = grouped(
            connection,
            "SELECT topic.name, COUNT(DISTINCT papertopic.paper_id) AS count FROM topic "
            "JOIN papertopic ON papertopic.topic_id=topic.topic_id "
            "GROUP BY topic.topic_id ORDER BY count DESC, topic.name LIMIT 12",
        )
        snapshot = {
            "available": True,
            "path": "data/papers.db",
            "sha256": sha256(DB),
            "bytes": DB.stat().st_size,
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "foreign_key_violation_count": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "entity_counts": counts,
            "extracted_paper_count": totals[0],
            "extracted_page_count": totals[1],
            "extracted_word_count": totals[2],
            "extracted_character_count": totals[3],
            "review_status_counts": status_tables,
        }
        return snapshot, years, paper_status, top_topics
    finally:
        connection.close()


def write_csv(name: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required evidence artefacts are missing: " + ", ".join(missing))

    phase1 = load("phase1") or {}
    retrieval = load("retrieval") or {}
    qa = load("qa") or {}
    recommendation = load("recommendation") or {}
    topics = load("topics") or {}
    authors = load("authors") or {}
    review = load("generated_review") or {}
    external = load("external_sanity") or {}
    performance = load("performance") or {}
    stored_performance_validation = load("performance_validation") or {}
    performance_validation = validate_performance_artifact(
        performance,
        expected_profile="full",
        expected_repetitions=3,
        expected_stages=list(FULL_REQUIRED_STAGES),
    )
    if performance_validation != stored_performance_validation:
        raise ValueError(
            "Strict performance validation does not match "
            "artifacts/phase6/performance/performance_validation.json"
        )
    database, years, paper_status, top_topics = database_snapshot()

    performance_summary = {
        "validation": performance_validation,
        "benchmark_id": performance["benchmark_id"],
        "profile": performance["profile"],
        "methodology": {
            key: value
            for key, value in performance["methodology"].items()
            if key != "runtime_root"
        },
        "hardware": performance["hardware"],
        "corpus": performance["corpus"],
        "results": {
            key: {
                "cold": value["cold"]["summary"],
                "warm": value["warm"]["summary"],
            }
            for key, value in performance["results"].items()
            if isinstance(value, dict) and "cold" in value
        },
        "ocr": performance["results"].get("ocr"),
        "execution_source": {
            boundary: {
                "commit": details["commit"],
                "benchmark_source_sha256": details["benchmark_source_sha256"],
                "benchmark_source_path": details["benchmark_source_path"],
            }
            for boundary, details in performance["execution_source"].items()
        },
        "limitations": performance["limitations"],
    }

    corpus = phase1["corpus"]
    review_counts = review.get("counts", {})
    payload = {
        "schema_version": 2,
        "claim_boundary": (
            "Frozen phase artefacts are authoritative for empirical results; the database section is a "
            "read-only operational snapshot. AI-reviewed silver results are not human validation."
        ),
        "generation_provenance": generation_provenance(),
        "corpus": corpus,
        "corpus_snapshot_id": phase1["indexes"]["dense"]["manifest"]["corpus"]["snapshot_id"],
        "corpus_snapshot_sha256": phase1["indexes"]["dense"]["manifest"]["corpus"]["snapshot_hash"],
        "database": database,
        "indexes": {
            name: {
                "status": value["status"],
                "indexed_chunks": value.get("indexed_chunk_count", value.get("manifest", {}).get("corpus", {}).get("eligible_chunk_count")),
                "index_sha256": value.get("actual_index_sha256"),
                "configuration": value.get("manifest", {}).get("configuration"),
            }
            for name, value in phase1["indexes"].items()
        },
        "section_silver": phase1["section_silver_validation"],
        "metadata_identity": phase1["metadata_identity"],
        "evaluation": {
            "retrieval": {
                "case_count": retrieval["dataset"]["case_count"],
                "dev_count": retrieval["dataset"]["dev_count"],
                "test_count": retrieval["dataset"]["test_count"],
                "test_results": retrieval["test_results"],
            },
            "qa": {"case_count": qa["case_count"], "counts": qa["counts"], "metrics": qa["metrics"]},
            "recommendation": {
                "profile_count": recommendation["profile_coverage"]["profile_count"],
                "arm_comparison": recommendation["metrics"]["arm_comparison"],
            },
            "topics": {
                "lexical_test": topics["methods"]["controlled_lexical"]["test"],
                "dense_test": topics["methods"]["dense_prototype"]["test"],
            },
            "authors": {
                "identity_counts": authors["identity_counts"],
                "possible_same_person_pair_count": len(authors["possible_same_person_pairs_not_merged"]),
                "audit_violation_counts": {
                    "excluded_evidence": authors["excluded_author_evidence_count"],
                    "alias_collision": authors["alias_collision_count"],
                    "authorship_mismatch": authors["authorship_mismatch_count"],
                    "overclaim": authors["overclaim_output_violation_count"],
                },
            },
            "generated_output_review": review_counts,
            "external_sanity": {
                "status": external.get("status"),
                "case_count": external.get("sanity_check", {}).get("case_count"),
                "top_1_matches": external.get("sanity_check", {}).get("top_1_matches"),
            },
            "performance": performance_summary,
        },
        "source_files": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
            }
            for name, path in SOURCES.items()
            if path.is_file()
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "evidence_snapshot.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv("year_distribution.csv", years, ["year", "count"])
    status_labels = {
        "eligible": "Eligible",
        "needs_review": "No text",
        "excluded_pdf_metadata_mismatch": "Mismatch",
    }
    write_csv(
        "paper_status.csv",
        [
            {"status": status_labels.get(str(row["status"]), str(row["status"])), "count": row["count"]}
            for row in paper_status
        ],
        ["status", "count"],
    )
    write_csv("top_topics.csv", top_topics, ["name", "count"])
    write_csv(
        "chunk_embedding_status.csv",
        [
            {"provider": "Keyword FTS", "indexed_chunks": corpus["eligible_chunk_count"]},
            {"provider": "Feature hashing", "indexed_chunks": corpus["eligible_chunk_count"]},
            {"provider": "Learned dense", "indexed_chunks": corpus["eligible_chunk_count"]},
        ],
        ["provider", "indexed_chunks"],
    )
    print(f"wrote={OUT / 'evidence_snapshot.json'}")
    print(f"corpus={payload['corpus_snapshot_id']} eligible_chunks={corpus['eligible_chunk_count']}")
    print(f"database_quick_check={database.get('quick_check')} review_events={database.get('entity_counts', {}).get('reviewevent')}")


if __name__ == "__main__":
    main()
