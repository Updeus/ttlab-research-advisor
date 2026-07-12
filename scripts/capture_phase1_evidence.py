#!/usr/bin/env python3
"""Capture a sanitized, path-independent Phase 1 corpus/index evidence record."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data/papers.db"
DEFAULT_OUTPUT = ROOT / "artifacts/phase1/phase1_evidence.json"
VECTOR_INDEXES = {
    "feature_hashing": ROOT / "data/indexes/feature_hashing_embeddings.json",
    "dense": ROOT / "data/indexes/dense_embeddings.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def query_counts(connection: sqlite3.Connection, sql: str) -> dict[str, int]:
    return {str(key): int(value) for key, value in connection.execute(sql)}


def query_scalar(connection: sqlite3.Connection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def vector_manifest(index_path: Path) -> dict[str, Any]:
    manifest_path = index_path.with_suffix(".manifest.json")
    if not index_path.exists() or not manifest_path.exists():
        return {
            "status": "missing",
            "index_path": relative_path(index_path),
            "manifest_path": relative_path(manifest_path),
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored_index = manifest.get("index") or {}
    actual_hash = sha256(index_path)
    return {
        "status": "ready" if stored_index.get("sha256") == actual_hash else "invalid",
        "index_path": relative_path(index_path),
        "manifest_path": relative_path(manifest_path),
        "index_size_bytes": index_path.stat().st_size,
        "actual_index_sha256": actual_hash,
        "manifest": {
            **manifest,
            "index": {
                **stored_index,
                "path": relative_path(index_path),
            },
        },
    }


def package_versions() -> dict[str, str | None]:
    names = (
        "sentence-transformers",
        "torch",
        "transformers",
        "huggingface-hub",
        "tokenizers",
        "safetensors",
        "numpy",
        "scikit-learn",
        "scipy",
    )
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def command_output(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def collect(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
    foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    keyword_metadata = {
        str(key): json.loads(value)
        for key, value in connection.execute("SELECT key, value FROM chunk_fts_metadata ORDER BY key")
    }
    excluded_rows = [
        {
            "paper_id": str(paper_id),
            "eligibility_status": str(status),
            "reason": reason,
            "chunk_count": int(chunk_count),
        }
        for paper_id, status, reason, chunk_count in connection.execute(
            """
            SELECT p.paper_id, p.corpus_eligibility_status, p.corpus_exclusion_reason, COUNT(c.chunk_id)
            FROM paper p LEFT JOIN chunk c ON c.paper_id = p.paper_id
            WHERE p.corpus_eligibility_status LIKE 'excluded_%'
               OR p.corpus_eligibility_status LIKE 'ineligible_%'
            GROUP BY p.paper_id, p.corpus_eligibility_status, p.corpus_exclusion_reason
            ORDER BY p.paper_id
            """
        )
    ]
    evidence = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "database": {
            "path": relative_path(database),
            "sha256": sha256(database),
            "quick_check": quick_check,
            "foreign_key_violations": foreign_key_violations,
        },
        "corpus": {
            "paper_count": query_scalar(connection, "SELECT COUNT(*) FROM paper"),
            "raw_chunk_count": query_scalar(connection, "SELECT COUNT(*) FROM chunk"),
            "eligible_paper_count": query_scalar(
                connection, "SELECT COUNT(*) FROM paper WHERE corpus_eligibility_status='eligible'"
            ),
            "eligible_chunk_count": query_scalar(
                connection,
                """
                SELECT COUNT(*) FROM chunk c JOIN paper p ON p.paper_id=c.paper_id
                WHERE p.corpus_eligibility_status='eligible'
                """,
            ),
            "eligibility_statuses": query_counts(
                connection,
                "SELECT corpus_eligibility_status, COUNT(*) FROM paper GROUP BY corpus_eligibility_status ORDER BY 1",
            ),
            "pdf_unavailability_reasons": query_counts(
                connection,
                "SELECT COALESCE(pdf_unavailability_reason, 'available'), COUNT(*) FROM paper GROUP BY 1 ORDER BY 1",
            ),
            "pdf_title_match_statuses": query_counts(
                connection,
                "SELECT pdf_title_match_status, COUNT(*) FROM paper GROUP BY pdf_title_match_status ORDER BY 1",
            ),
            "extraction_content_types": query_counts(
                connection,
                "SELECT extraction_content_type, COUNT(*) FROM paper GROUP BY extraction_content_type ORDER BY 1",
            ),
            "ocr_statuses": query_counts(
                connection,
                "SELECT ocr_status, COUNT(*) FROM paper GROUP BY ocr_status ORDER BY 1",
            ),
            "section_counts_all": query_counts(
                connection, "SELECT section, COUNT(*) FROM chunk GROUP BY section ORDER BY 1"
            ),
            "section_counts_eligible": query_counts(
                connection,
                """
                SELECT c.section, COUNT(*) FROM chunk c JOIN paper p ON p.paper_id=c.paper_id
                WHERE p.corpus_eligibility_status='eligible' GROUP BY c.section ORDER BY c.section
                """,
            ),
            "excluded_records": excluded_rows,
        },
        "metadata_identity": {
            "author_count": query_scalar(connection, "SELECT COUNT(*) FROM author"),
            "author_alias_count": query_scalar(connection, "SELECT COUNT(*) FROM authoralias"),
            "author_identity_statuses": query_counts(
                connection, "SELECT identity_status, COUNT(*) FROM author GROUP BY identity_status ORDER BY 1"
            ),
            "click_to_view_author_count": query_scalar(
                connection, "SELECT COUNT(*) FROM author WHERE lower(trim(name))='click to view' AND paper_count>0"
            ),
            "verified_doi_count": query_scalar(connection, "SELECT COUNT(*) FROM paper WHERE doi IS NOT NULL AND trim(doi)<>''"),
            "verified_abstract_count": query_scalar(
                connection, "SELECT COUNT(*) FROM paper WHERE abstract IS NOT NULL AND trim(abstract)<>''"
            ),
            "verified_keyword_count": query_scalar(
                connection,
                """
                SELECT COUNT(*) FROM paper
                WHERE keywords IS NOT NULL
                  AND lower(trim(keywords)) NOT IN ('', '[]', '{}', 'null')
                """,
            ),
            "venue_count": query_scalar(
                connection, "SELECT COUNT(*) FROM paper WHERE venue IS NOT NULL AND trim(venue)<>''"
            ),
        },
        "indexes": {
            "keyword": {
                "status": "ready"
                if keyword_metadata.get("completeness_status") == "complete"
                and int(keyword_metadata.get("indexed_chunk_count", -1))
                == query_scalar(connection, "SELECT COUNT(*) FROM chunk_fts")
                else "invalid",
                "indexed_chunk_count": query_scalar(connection, "SELECT COUNT(*) FROM chunk_fts"),
                "metadata": keyword_metadata,
            },
            **{name: vector_manifest(path) for name, path in VECTOR_INDEXES.items()},
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": package_versions(),
            "git_commit": command_output(["git", "rev-parse", "HEAD"])["stdout"],
            "git_status": command_output(["git", "status", "--short"])["stdout"].splitlines(),
        },
        "section_silver_validation": command_output(
            [
                "python",
                "data/evaluation/validate_section_quality_silver_v1.py",
                "--database",
                relative_path(database),
                "--evaluate-current",
            ]
        ),
    }
    connection.close()
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = collect(args.database)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(f"wrote={relative_path(args.out)} sha256={sha256(args.out)}")


if __name__ == "__main__":
    main()
