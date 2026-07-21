#!/usr/bin/env python3
"""Fail closed when the Phase 4 topic/author silver evidence drifts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
MANIFEST = ROOT / "data/evaluation/topic_author_silver_v1.manifest.json"
SCHEMA = ROOT / "data/evaluation/topic_author_silver_v1.schema.json"
DATABASE = ROOT / "data/papers.db"
DENSE_INDEX = ROOT / "data/indexes/dense_embeddings.json"
DENSE_MANIFEST = ROOT / "data/indexes/dense_embeddings.manifest.json"
FROZEN_PHASE1_EVIDENCE = ROOT / "artifacts/phase1/phase1_evidence.json"
BINDING_RECEIPT = ROOT / "artifacts/phase4/topic_author/topic_silver_current_binding.json"
EXCLUDED_IDS = {
    "pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f",
    "vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8",
}
CHUNK_ID_RE = re.compile(r"^(?P<paper_id>.+)-chunk-(?P<chunk_index>\d{4})-[0-9a-f]{12}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return path.name


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_frozen_phase1_evidence(
    path: Path,
    *,
    expected_snapshot_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the tracked historical evidence even after a full run regenerates its working copy."""

    working_payload = json.loads(path.read_text(encoding="utf-8"))
    working_corpus = working_payload["indexes"]["dense"]["manifest"]["corpus"]
    if working_corpus["snapshot_hash"] == expected_snapshot_hash:
        return working_payload, {
            "source": "working_tree",
            "path": display_path(path),
            "sha256": sha256_file(path),
        }

    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(
            "frozen Phase 1 evidence differs from the silver snapshot and is outside the repository"
        ) from error
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(
            "frozen Phase 1 evidence differs from the silver snapshot and the tracked commit blob is unavailable"
        )
    try:
        tracked_payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("tracked Phase 1 evidence is not valid UTF-8 JSON") from error
    tracked_corpus = tracked_payload["indexes"]["dense"]["manifest"]["corpus"]
    if tracked_corpus["snapshot_hash"] != expected_snapshot_hash:
        raise ValueError("tracked Phase 1 evidence does not match the frozen silver snapshot")
    return tracked_payload, {
        "source": "tracked_commit_blob",
        "path": relative,
        "git_revision": "HEAD",
        "sha256": sha256_bytes(result.stdout),
        "working_tree_snapshot_hash": working_corpus["snapshot_hash"],
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bounded_snippet(value: str, limit: int = 480) -> str:
    """Reproduce the frozen builder's whitespace normalization and bound."""

    cleaned = " ".join(str(value or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip(" ,.;:") + "..."


def frozen_chunk_index(chunk_id: str, paper_id: str) -> int:
    match = CHUNK_ID_RE.fullmatch(chunk_id)
    if match is None or match.group("paper_id") != paper_id:
        raise ValueError(f"non-canonical frozen chunk ID: {chunk_id}")
    return int(match.group("chunk_index"))


def resolve_source_chunk(
    connection: sqlite3.Connection,
    *,
    case_id: str,
    paper_id: str,
    evidence: dict[str, Any],
    current_dense_chunk_ids: set[str],
) -> dict[str, Any]:
    """Bind one frozen source excerpt to the current corpus without relabeling.

    Content-derived chunk IDs are authoritative when they still exist. If one
    is absent after a deterministic rebuild, the only accepted fallback is one
    row at the same paper, encoded chunk index, page interval, and section whose
    bounded source excerpt is byte-for-byte identical to the persisted silver
    excerpt. The current row must also be in the active dense-index manifest.
    """

    frozen_id = str(evidence["chunk_id"])
    frozen_hash = str(evidence["source_hash"])
    chunk_index = frozen_chunk_index(frozen_id, paper_id)
    row = connection.execute(
        """
        SELECT chunk_id,paper_id,chunk_index,page_start,page_end,section,source_hash,text
        FROM chunk WHERE chunk_id=?
        """,
        (frozen_id,),
    ).fetchone()
    resolution = "exact_chunk_id"
    if row is None:
        rows = connection.execute(
            """
            SELECT chunk_id,paper_id,chunk_index,page_start,page_end,section,source_hash,text
            FROM chunk
            WHERE paper_id=? AND chunk_index=?
              AND page_start IS ? AND page_end IS ? AND section=?
            ORDER BY chunk_id
            """,
            (
                paper_id,
                chunk_index,
                evidence.get("page_start"),
                evidence.get("page_end"),
                evidence.get("section"),
            ),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                f"{case_id}: stable paper/chunk/page/section locator matched {len(rows)} rows"
            )
        row = rows[0]
        resolution = "stable_paper_chunk_page_section_locator"

    if row["paper_id"] != paper_id:
        raise ValueError(f"{case_id}: source chunk belongs to another paper")
    if row["chunk_id"] not in current_dense_chunk_ids:
        raise ValueError(f"{case_id}: resolved source chunk is absent from the active dense corpus")
    if resolution == "exact_chunk_id" and row["source_hash"] != frozen_hash:
        raise ValueError(f"{case_id}: exact source chunk hash drift")
    current_excerpt = bounded_snippet(str(row["text"] or ""))
    if current_excerpt != evidence["text"]:
        raise ValueError(f"{case_id}: persisted source excerpt differs at the current locator")

    return {
        "case_id": case_id,
        "paper_id": paper_id,
        "resolution": resolution,
        "chunk_index": int(row["chunk_index"]),
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "section": row["section"],
        "frozen_chunk_id": frozen_id,
        "current_chunk_id": str(row["chunk_id"]),
        "frozen_source_hash": frozen_hash,
        "current_source_hash": str(row["source_hash"]),
        "persisted_excerpt_sha256": sha256_bytes(evidence["text"].encode("utf-8")),
        "current_excerpt_sha256": sha256_bytes(current_excerpt.encode("utf-8")),
        "persisted_excerpt_exact_match": True,
    }


def validate(
    dataset: Path = DATASET,
    *,
    manifest_path: Path = MANIFEST,
    schema_path: Path = SCHEMA,
    database: Path = DATABASE,
    dense_index: Path = DENSE_INDEX,
    dense_manifest_path: Path = DENSE_MANIFEST,
    frozen_phase1_evidence: Path = FROZEN_PHASE1_EVIDENCE,
    output_json: Path | None = None,
) -> dict[str, Any]:
    raw = dataset.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    dense_manifest = json.loads(dense_manifest_path.read_text(encoding="utf-8"))
    try:
        phase1, frozen_phase1_provenance = load_frozen_phase1_evidence(
            frozen_phase1_evidence,
            expected_snapshot_hash=manifest["corpus"]["snapshot_hash"],
        )
    except (KeyError, ValueError, FileNotFoundError, json.JSONDecodeError) as error:
        raise SystemExit(f"topic/author silver validation failed:\n- {error}") from error
    frozen_corpus = phase1["indexes"]["dense"]["manifest"]["corpus"]
    current_corpus = dense_manifest["corpus"]
    current_dense_chunk_ids = {str(item["chunk_id"]) for item in current_corpus["eligible_chunks"]}
    frozen_dense_chunks = {
        str(item["chunk_id"]): str(item["source_hash"])
        for item in frozen_corpus["eligible_chunks"]
    }
    records = load_jsonl(dataset)
    errors: list[str] = []
    case_bindings: list[dict[str, Any]] = []

    if sha256_bytes(raw) != manifest["dataset_sha256"]:
        errors.append("dataset SHA-256 does not match manifest")
    if frozen_corpus["snapshot_hash"] != manifest["corpus"]["snapshot_hash"]:
        errors.append("frozen Phase 1 evidence and silver manifest corpus snapshots differ")
    if frozen_corpus["eligible_paper_count"] != manifest["corpus"]["eligible_paper_count"]:
        errors.append("frozen Phase 1 paper count and silver manifest differ")
    if frozen_corpus["eligible_chunk_count"] != manifest["corpus"]["eligible_chunk_count"]:
        errors.append("frozen Phase 1 chunk count and silver manifest differ")
    if sha256_file(dense_index) != dense_manifest["index"]["sha256"]:
        errors.append("active dense index checksum differs from its manifest")
    if len(current_dense_chunk_ids) != current_corpus["eligible_chunk_count"]:
        errors.append("active dense manifest has duplicate or missing eligible chunk identities")

    validator = Draft202012Validator(schema)
    for index, record in enumerate(records, start=1):
        for error in validator.iter_errors(record):
            errors.append(f"line {index}: schema: {error.message}")
    if len(records) != manifest["case_count"] or len(records) < 40:
        errors.append("case count is below the declared stratified sample")
    if len({record["case_id"] for record in records}) != len(records):
        errors.append("case IDs are not unique")
    if len({record["paper_id"] for record in records}) != len(records):
        errors.append("paper IDs are not unique")
    if {record["split"] for record in records} != {"dev", "test"}:
        errors.append("both dev and test splits are required")
    if {record["stratum"] for record in records} != {"single_label", "multi_label", "other_unknown"}:
        errors.append("single-label, multi-label, and other/unknown strata are required")
    label_support = {
        label: sum(label in record["final_labels"] for record in records)
        for label in schema["properties"]["final_labels"]["items"]["enum"]
    }
    if set(label_support) != set(manifest["label_support"]) or label_support != manifest["label_support"]:
        errors.append("label support does not match the manifest")
    if any(value < 1 for value in label_support.values()):
        errors.append("every controlled label must have at least one source-backed silver case")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        for record in records:
            paper = connection.execute(
                "SELECT paper_id,title,corpus_eligibility_status FROM paper WHERE paper_id=?",
                (record["paper_id"],),
            ).fetchone()
            if paper is None:
                errors.append(f"{record['case_id']}: missing paper")
                continue
            if paper["corpus_eligibility_status"] != "eligible" or paper["paper_id"] in EXCLUDED_IDS:
                errors.append(f"{record['case_id']}: paper is not in the eligible current corpus")
            if paper["title"] != record["title"]:
                errors.append(f"{record['case_id']}: title drift")
            if record["corpus"] != manifest["corpus"]:
                errors.append(f"{record['case_id']}: frozen corpus descriptor drift")
            if record["final_other_unknown"] != (not record["final_labels"]):
                errors.append(f"{record['case_id']}: other/unknown is inconsistent with final labels")
            if record["stratum"] == "other_unknown" and record["final_labels"]:
                errors.append(f"{record['case_id']}: other/unknown case has a controlled label")
            passes = record["review_passes"]
            if [item["pass_id"] for item in passes] != ["create", "verify"]:
                errors.append(f"{record['case_id']}: required review passes are absent")
            if any(item["reviewer_type"] != "ai" for item in passes):
                errors.append(f"{record['case_id']}: reviewer type must be AI")
            if sorted(passes[1]["labels"]) != sorted(record["final_labels"]):
                errors.append(f"{record['case_id']}: final labels do not match verification pass")
            for evidence in record["evidence"]:
                if evidence["evidence_type"] == "paper_title":
                    if sha256_bytes(evidence["text"].encode("utf-8")) != evidence["sha256"]:
                        errors.append(f"{record['case_id']}: title evidence hash drift")
                    if evidence["text"] != paper["title"]:
                        errors.append(f"{record['case_id']}: title evidence differs from current paper title")
                    continue
                if frozen_dense_chunks.get(evidence["chunk_id"]) != evidence["source_hash"]:
                    errors.append(f"{record['case_id']}: source chunk is absent from the frozen Phase 1 corpus")
                    continue
                try:
                    case_bindings.append(
                        resolve_source_chunk(
                            connection,
                            case_id=record["case_id"],
                            paper_id=record["paper_id"],
                            evidence=evidence,
                            current_dense_chunk_ids=current_dense_chunk_ids,
                        )
                    )
                except ValueError as error:
                    errors.append(str(error))
    finally:
        connection.close()

    expected_source_evidence = sum(
        item["evidence_type"] == "source_chunk"
        for record in records
        for item in record["evidence"]
    )
    if len(case_bindings) != expected_source_evidence:
        errors.append(
            f"validated source binding count {len(case_bindings)} differs from expected {expected_source_evidence}"
        )
    binding_keys = {(item["case_id"], item["frozen_chunk_id"]) for item in case_bindings}
    if len(binding_keys) != len(case_bindings):
        errors.append("current source bindings are not unique per case and frozen chunk")
    if errors:
        raise SystemExit("topic/author silver validation failed:\n- " + "\n- ".join(errors))

    resolutions = Counter(item["resolution"] for item in case_bindings)
    drifts = [
        item
        for item in case_bindings
        if item["frozen_chunk_id"] != item["current_chunk_id"]
        or item["frozen_source_hash"] != item["current_source_hash"]
    ]
    result = {
        "schema_version": 2,
        "status": "PASS",
        "reviewer_type": "ai",
        "human_validation": False,
        "cases": len(records),
        "dataset": {
            "path": display_path(dataset),
            "sha256": manifest["dataset_sha256"],
        },
        "database": {
            "path": display_path(database),
            "sha256": sha256_file(database),
        },
        "dense_index": {
            "path": display_path(dense_index),
            "sha256": dense_manifest["index"]["sha256"],
            "manifest_path": display_path(dense_manifest_path),
            "manifest_sha256": sha256_file(dense_manifest_path),
        },
        "frozen_annotation_corpus": manifest["corpus"],
        "frozen_phase1_evidence": frozen_phase1_provenance,
        "current_execution_corpus": {
            key: current_corpus[key]
            for key in ("snapshot_id", "snapshot_hash", "eligible_paper_count", "eligible_chunk_count")
        },
        "split_counts": manifest["split_counts"],
        "stratum_counts": manifest["stratum_counts"],
        "pass_exact_agreement": manifest["pass_exact_agreement"],
        "current_case_binding": {
            "resolution_counts": dict(sorted(resolutions.items())),
            "source_snapshot_drift_count": len(drifts),
            "source_snapshot_drifts": drifts,
            "case_bindings": case_bindings,
            "interpretation": (
                "The labels remain the frozen AI-reviewed silver judgments. Current evaluation uses exact "
                "content-derived chunk IDs where available. A missing ID may bind only to one row at the "
                "same paper, encoded chunk index, page interval, and section when the persisted bounded "
                "excerpt is byte-for-byte unchanged and the row belongs to the active dense corpus. The "
                "frozen and current corpus identities remain distinct; this is current-snapshot scoring, "
                "not exact reproduction or relabeling of the historical snapshot."
            ),
        },
    }
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--dense-index", type=Path, default=DENSE_INDEX)
    parser.add_argument("--dense-manifest", type=Path, default=DENSE_MANIFEST)
    parser.add_argument("--json-out", type=Path, default=BINDING_RECEIPT)
    args = parser.parse_args()
    result = validate(
        args.dataset,
        database=args.database,
        dense_index=args.dense_index,
        dense_manifest_path=args.dense_manifest,
        output_json=args.json_out,
    )
    print(json.dumps({
        "status": result["status"],
        "cases": result["cases"],
        "reviewer_type": result["reviewer_type"],
        "human_validation": result["human_validation"],
        "frozen_annotation_corpus": result["frozen_annotation_corpus"],
        "current_execution_corpus": result["current_execution_corpus"],
        "current_case_binding": {
            "resolution_counts": result["current_case_binding"]["resolution_counts"],
            "source_snapshot_drift_count": result["current_case_binding"]["source_snapshot_drift_count"],
            "source_snapshot_drifts": result["current_case_binding"]["source_snapshot_drifts"],
        },
        "binding_receipt": display_path(args.json_out),
    }, indent=2))


if __name__ == "__main__":
    main()
