#!/usr/bin/env python3
"""Collect a reproducible, read-only snapshot of the local project evidence.

The generated files are committed so the thesis can build without the ignored
runtime database. Re-run this script whenever the local demo data changes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "thesis" / "generated"
DB_PATH = ROOT / "data" / "papers.db"
SEED_PATH = ROOT / "data" / "seed" / "papers.json"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_sha256(paths: Iterable[Path]) -> str:
    manifest = hashlib.sha256()
    for path in sorted(paths):
        line = f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n"
        manifest.update(line.encode("utf-8"))
    return manifest.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, record, strict=True)) for record in cursor.fetchall()]


def scalar(connection: sqlite3.Connection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        scalar(
            connection,
            "SELECT COUNT(*) FROM sqlite_master "
            f"WHERE type='table' AND name='{table.replace(chr(39), chr(39) * 2)}'",
        )
    )


def database_snapshot() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"available": False, "path": str(DB_PATH.relative_to(ROOT))}

    connection = sqlite3.connect(DB_PATH)
    try:
        entity_tables = [
            "paper",
            "author",
            "chunk",
            "raganswer",
            "thesisrecommendation",
            "paperartifact",
            "topic",
            "reviewevent",
            "papertopic",
            "authortopic",
        ]
        counts = {
            table: scalar(connection, f"SELECT COUNT(*) FROM {table}")
            for table in entity_tables
            if table_exists(connection, table)
        }
        return {
            "available": True,
            "path": str(DB_PATH.relative_to(ROOT)),
            "bytes": DB_PATH.stat().st_size,
            "sha256": sha256(DB_PATH),
            "entity_counts": counts,
            "paper_status": rows(
                connection,
                "SELECT ingestion_status, pdf_text_status, review_status, COUNT(*) AS count "
                "FROM paper GROUP BY ingestion_status, pdf_text_status, review_status "
                "ORDER BY count DESC",
            ),
            "years": rows(
                connection,
                "SELECT year, COUNT(*) AS count FROM paper GROUP BY year ORDER BY year",
            ),
            "chunk_embedding_status": rows(
                connection,
                "SELECT embedding_status, COUNT(*) AS count, "
                "ROUND(AVG(token_count_estimate), 1) AS average_estimated_tokens "
                "FROM chunk GROUP BY embedding_status ORDER BY count DESC",
            ),
            "chunk_sections": rows(
                connection,
                "SELECT section, COUNT(*) AS count, "
                "ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM chunk), 2) AS percentage "
                "FROM chunk GROUP BY section ORDER BY count DESC",
            ),
            "corpus_totals": rows(
                connection,
                "SELECT SUM(total_word_count) AS words, SUM(total_char_count) AS characters, "
                "SUM(page_count) AS pages, SUM(chunk_count) AS chunks_reported, "
                "ROUND(AVG(chunk_count), 2) AS average_chunks_per_extracted_paper "
                "FROM paper WHERE pdf_text_status='extracted'",
            )[0]
            | {
                "chunk_words_with_overlap": scalar(connection, "SELECT SUM(word_count) FROM chunk"),
                "chunk_to_source_word_ratio": round(
                    scalar(connection, "SELECT SUM(word_count) FROM chunk")
                    / max(
                        scalar(
                            connection,
                            "SELECT SUM(total_word_count) FROM paper WHERE pdf_text_status='extracted'",
                        ),
                        1,
                    ),
                    3,
                ),
            },
            "metadata_completeness": {
                "with_doi": scalar(connection, "SELECT COUNT(*) FROM paper WHERE COALESCE(TRIM(doi), '') <> ''"),
                "with_abstract": scalar(
                    connection, "SELECT COUNT(*) FROM paper WHERE COALESCE(TRIM(abstract), '') <> ''"
                ),
                "with_pdf_url": scalar(
                    connection, "SELECT COUNT(*) FROM paper WHERE COALESCE(TRIM(pdf_url), '') <> ''"
                ),
                "with_reviewed_status": scalar(
                    connection, "SELECT COUNT(*) FROM paper WHERE review_status IN ('reviewed', 'approved')"
                ),
            },
            "rag_answers": rows(
                connection,
                "SELECT provider, model, grounding_status, review_status, COUNT(*) AS count "
                "FROM raganswer GROUP BY provider, model, grounding_status, review_status "
                "ORDER BY count DESC",
            ),
            "recommendations": rows(
                connection,
                "SELECT provider, model, grounding_status, review_status, COUNT(*) AS count "
                "FROM thesisrecommendation GROUP BY provider, model, grounding_status, review_status "
                "ORDER BY count DESC",
            ),
            "artifacts": rows(
                connection,
                "SELECT artifact_type, generation_status, grounding_status, review_status, COUNT(*) AS count "
                "FROM paperartifact "
                "GROUP BY artifact_type, generation_status, grounding_status, review_status "
                "ORDER BY artifact_type",
            ),
            "top_topics": rows(
                connection,
                "SELECT topic.name, COUNT(DISTINCT papertopic.paper_id) AS paper_count "
                "FROM topic JOIN papertopic USING(topic_id) GROUP BY topic.topic_id "
                "ORDER BY paper_count DESC, topic.name LIMIT 12",
            ),
            "top_authors": rows(
                connection,
                "SELECT name, paper_count FROM author ORDER BY paper_count DESC, name LIMIT 12",
            ),
            "date_bounds": {
                "paper_first_created": scalar(connection, "SELECT MIN(created_at) FROM paper"),
                "paper_last_updated": scalar(connection, "SELECT MAX(updated_at) FROM paper"),
                "answer_first_created": scalar(connection, "SELECT MIN(created_at) FROM raganswer"),
                "answer_last_created": scalar(connection, "SELECT MAX(created_at) FROM raganswer"),
            },
        }
    finally:
        connection.close()


def seed_snapshot() -> dict[str, Any]:
    if not SEED_PATH.exists():
        return {"available": False, "path": str(SEED_PATH.relative_to(ROOT))}
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else []
    return {
        "available": True,
        "path": str(SEED_PATH.relative_to(ROOT)),
        "bytes": SEED_PATH.stat().st_size,
        "sha256": sha256(SEED_PATH),
        "records": len(records),
        "years": dict(sorted(Counter(record.get("year") for record in records).items(), key=lambda item: str(item[0]))),
        "records_with_pdf_url": sum(bool(record.get("pdf_url")) for record in records),
        "records_with_source_url": sum(bool(record.get("source_url")) for record in records),
    }


def code_inventory() -> dict[str, Any]:
    excluded_parts = {".git", ".venv", "node_modules", "dist", "build", "tmp", ".pytest_cache"}
    extensions = {".py", ".ts", ".tsx", ".css", ".md", ".sh", ".json"}
    counts: Counter[str] = Counter()
    lines: Counter[str] = Counter()
    completed = subprocess.run(
        ["rg", "--files"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    candidates = completed.stdout.splitlines() if completed.returncode == 0 else git("ls-files").splitlines()
    for relative in candidates:
        path = ROOT / relative
        if not path.is_file() or excluded_parts.intersection(Path(relative).parts):
            continue
        if path.suffix not in extensions:
            continue
        counts[path.suffix] += 1
        try:
            lines[path.suffix] += len(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            continue
    return {"file_counts_by_extension": dict(counts), "line_counts_by_extension": dict(lines)}


def evaluation_snapshot() -> dict[str, Any]:
    evaluation_dir = ROOT / "data" / "evaluation"
    filenames = [
        "retrieval_eval_results.json",
        "qa_eval_results.json",
        "extension_eval_results.json",
        "artifact_eval_results.json",
        "ollama_benchmark_results.json",
    ]
    result: dict[str, Any] = {}
    for filename in filenames:
        path = evaluation_dir / filename
        if not path.exists():
            result[filename] = {"status": "not_run"}
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            result[filename] = {
                "status": "available",
                "sha256": sha256(path),
                "payload": payload,
            }
        except json.JSONDecodeError as exc:
            result[filename] = {"status": "invalid", "error": str(exc)}
    return result


def semantic_index_snapshot() -> dict[str, Any]:
    path = ROOT / "data" / "indexes" / "hashing_embeddings.json"
    if not path.exists():
        return {"status": "missing", "path": str(path.relative_to(ROOT))}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "status": "invalid",
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "error": str(exc),
        }
    records = payload.get("records", []) if isinstance(payload, dict) else []
    return {
        "status": "ready",
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "provider": payload.get("provider"),
        "dimensions": payload.get("dimensions"),
        "created_at": payload.get("created_at"),
        "record_count": len(records),
    }


def write_csv(path: Path, records: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fieldnames})


def write_plot_data(snapshot: dict[str, Any]) -> None:
    database = snapshot["database"]
    if not database.get("available"):
        return
    write_csv(
        OUT / "paper_status.csv",
        database["paper_status"],
        ["ingestion_status", "pdf_text_status", "review_status", "count"],
    )
    write_csv(OUT / "year_distribution.csv", database["years"], ["year", "count"])
    write_csv(
        OUT / "chunk_embedding_status.csv",
        database["chunk_embedding_status"],
        ["embedding_status", "count", "average_estimated_tokens"],
    )
    write_csv(OUT / "top_topics.csv", database["top_topics"], ["name", "paper_count"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dirty_lines = [line for line in git("status", "--short").splitlines() if line]
    commits = []
    for line in git("log", "--reverse", "--format=%h|%cI|%s").splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"commit": parts[0], "timestamp": parts[1], "subject": parts[2]})
    pdf_paths = list((ROOT / "data" / "pdfs").glob("*.pdf"))
    snapshot = {
        "snapshot_generated_at_utc": datetime.now(UTC).isoformat(),
        "repository": {
            "root": str(ROOT),
            "head_commit": git("rev-parse", "HEAD"),
            "head_short": git("rev-parse", "--short", "HEAD"),
            "head_subject": git("log", "-1", "--format=%s"),
            "head_timestamp": git("log", "-1", "--format=%cI"),
            "branch": git("branch", "--show-current"),
            "dirty": bool(dirty_lines),
            "status_short": dirty_lines,
            "commits": commits,
        },
        "seed": seed_snapshot(),
        "database": database_snapshot(),
        "filesystem_counts": {
            "pdfs": len(pdf_paths),
            "pdf_bytes": sum(path.stat().st_size for path in pdf_paths),
            "pdf_checksum_manifest_sha256": manifest_sha256(pdf_paths),
            "extracted_json": len(list((ROOT / "data" / "extracted_text").glob("*.json"))),
            "extracted_text": len(list((ROOT / "data" / "extracted_text").glob("*.txt"))),
            "chunk_files": len(list((ROOT / "data" / "chunks").glob("*.json"))),
        },
        "evaluation": evaluation_snapshot(),
        "semantic_index": semantic_index_snapshot(),
        "code_inventory": code_inventory(),
    }
    (OUT / "evidence_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_plot_data(snapshot)
    print(f"wrote={OUT / 'evidence_snapshot.json'}")
    print(f"head={snapshot['repository']['head_short']} dirty={snapshot['repository']['dirty']}")
    print(f"database_available={snapshot['database']['available']}")


if __name__ == "__main__":
    main()
