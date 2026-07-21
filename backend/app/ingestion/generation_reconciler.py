from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import get_settings
from app.db import create_db_and_tables, engine
from app.indexing.chunker import (
    CHUNKER_ALGORITHM_VERSION,
    CHUNK_ARTIFACT_CONTRACT,
    DEFAULT_MAX_CHARS,
    DEFAULT_OVERLAP_WORDS,
    DEFAULT_TARGET_WORDS,
    canonical_chunks_sha256,
    chunk_manifest_path,
    db_chunk_payload,
    validate_extraction_artifact_link,
)
from app.ingestion.manual_import import invalidate_generated_outputs_for_paper
from app.ingestion.pdf_parser import canonical_json_sha256, file_hash, safe_output_path
from app.models import Chunk, Paper


SHA256_RE = re.compile(r"[0-9a-f]{64}")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _within(path: Path, directory: Path) -> bool:
    resolved = path.resolve()
    root = directory.resolve()
    return resolved == root or root in resolved.parents


def _resolved_project_path(value: str | None, project_root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _expected_extraction_generation(extracted: dict[str, Any]) -> str:
    payload = {
        "paper_id": extracted.get("paper_id"),
        "input_pdf_sha256": extracted.get("input_pdf_sha256"),
        "extraction_config": extracted.get("extraction_config"),
        "text_artifact_sha256": extracted.get("text_artifact_sha256"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_extraction(
    paper: Paper,
    *,
    project_root: Path,
    extraction_dir: Path,
    pdf_dir: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    expected_json_path = safe_output_path(extraction_dir, paper.paper_id, ".json")
    recorded_json_path = _resolved_project_path(paper.extracted_json_path, project_root)
    if recorded_json_path is None:
        return None, "missing_extraction_manifest_path"
    if not _within(recorded_json_path, extraction_dir) or recorded_json_path.resolve() != expected_json_path.resolve():
        return None, "unsafe_or_unexpected_extraction_manifest_path"
    if not recorded_json_path.is_file():
        return None, "missing_extraction_manifest"
    try:
        extracted = _load_json(recorded_json_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unreadable_extraction_manifest"
    if not isinstance(extracted, dict):
        return None, "invalid_extraction_manifest_schema"
    if str(extracted.get("paper_id") or "") != paper.paper_id:
        return None, "extraction_paper_id_mismatch"
    if str(extracted.get("extraction_status") or "") != "extracted":
        return None, "extraction_not_successful"

    text_path = _resolved_project_path(str(extracted.get("full_text_path") or ""), project_root)
    expected_text_path = safe_output_path(extraction_dir, paper.paper_id, ".txt")
    if text_path is None or not _within(text_path, extraction_dir) or text_path.resolve() != expected_text_path.resolve():
        return None, "unsafe_or_unexpected_extraction_text_path"
    # The shared validator resolves relative paths from the process working
    # directory. Supply the already-validated absolute mirror path so this
    # command behaves consistently from any operator directory.
    extracted = dict(extracted)
    extracted["full_text_path"] = str(text_path)
    valid, reason = validate_extraction_artifact_link(extracted)
    if not valid:
        return None, str(reason or "invalid_extraction_artifact")
    if str(extracted.get("artifact_generation_id")) != _expected_extraction_generation(extracted):
        return None, "extraction_generation_recompute_mismatch"

    pdf_path = _resolved_project_path(paper.local_pdf_path, project_root)
    manifest_pdf_path = _resolved_project_path(str(extracted.get("local_pdf_path") or ""), project_root)
    if pdf_path is None or manifest_pdf_path is None:
        return None, "missing_input_pdf_path"
    if not _within(pdf_path, pdf_dir) or not _within(manifest_pdf_path, pdf_dir):
        return None, "unsafe_input_pdf_path"
    if pdf_path.resolve() != manifest_pdf_path.resolve():
        return None, "input_pdf_path_mismatch"
    if not pdf_path.is_file():
        return None, "missing_input_pdf"
    if file_hash(pdf_path) != str(extracted.get("input_pdf_sha256") or ""):
        return None, "input_pdf_hash_mismatch"
    return extracted, None


def _validate_chunk_manifest_configuration(manifest: dict[str, Any]) -> bool:
    configuration = manifest.get("chunker_configuration")
    if not isinstance(configuration, dict):
        return False
    min_chars = configuration.get("min_chars")
    return (
        configuration.get("algorithm_version") == CHUNKER_ALGORITHM_VERSION
        and configuration.get("target_words") == DEFAULT_TARGET_WORDS
        and configuration.get("max_chars") == DEFAULT_MAX_CHARS
        and configuration.get("overlap_words") == DEFAULT_OVERLAP_WORDS
        and isinstance(min_chars, int)
        and not isinstance(min_chars, bool)
        and min_chars >= 0
    )


def _validate_chunks(
    paper: Paper,
    extracted: dict[str, Any],
    database_chunks: list[Chunk],
    *,
    chunks_dir: Path,
) -> tuple[str | None, str | None]:
    chunk_path = chunks_dir / f"{paper.paper_id}.json"
    if not _within(chunk_path, chunks_dir):
        return None, "unsafe_chunk_artifact_path"
    manifest_path = chunk_manifest_path(chunk_path)
    if not chunk_path.is_file():
        return None, "missing_chunk_json"
    if not manifest_path.is_file():
        return None, "missing_chunk_manifest"
    try:
        file_chunks = _load_json(chunk_path)
        manifest = _load_json(manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unreadable_chunk_artifact"
    if not isinstance(file_chunks, list) or not isinstance(manifest, dict):
        return None, "invalid_chunk_artifact_schema"
    if manifest.get("artifact_contract") != CHUNK_ARTIFACT_CONTRACT:
        return None, "invalid_chunk_artifact_contract"
    if str(manifest.get("paper_id") or "") != paper.paper_id:
        return None, "chunk_manifest_paper_id_mismatch"
    extraction_generation_id = str(extracted.get("artifact_generation_id") or "")
    if str(manifest.get("extraction_artifact_generation_id") or "") != extraction_generation_id:
        return None, "chunk_extraction_generation_mismatch"
    if str(manifest.get("extraction_text_artifact_sha256") or "") != str(
        extracted.get("text_artifact_sha256") or ""
    ):
        return None, "chunk_extraction_text_hash_mismatch"
    if not _validate_chunk_manifest_configuration(manifest):
        return None, "unsupported_chunker_configuration"
    if not file_chunks:
        return None, "empty_chunk_artifact"
    if int(manifest.get("chunk_count") or -1) != len(file_chunks):
        return None, "chunk_manifest_count_mismatch"
    file_ids = [str(item.get("chunk_id") or "") for item in file_chunks if isinstance(item, dict)]
    if len(file_ids) != len(file_chunks) or not all(file_ids) or len(file_ids) != len(set(file_ids)):
        return None, "invalid_or_duplicate_chunk_ids"
    if list(manifest.get("chunk_ids") or []) != file_ids:
        return None, "chunk_manifest_id_mismatch"
    chunk_generation_id = str(manifest.get("chunks_sha256") or "")
    if not SHA256_RE.fullmatch(chunk_generation_id):
        return None, "invalid_chunk_generation_id"
    if canonical_chunks_sha256(file_chunks) != chunk_generation_id:
        return None, "chunk_json_hash_mismatch"
    for record in file_chunks:
        if str(record.get("paper_id") or "") != paper.paper_id:
            return None, "chunk_record_paper_id_mismatch"
        source_hash = str(record.get("source_hash") or "")
        if source_hash != hashlib.sha256(str(record.get("text") or "").encode("utf-8")).hexdigest():
            return None, "chunk_source_hash_mismatch"
    if len(database_chunks) != len(file_chunks):
        return None, "chunk_database_count_mismatch"
    if canonical_chunks_sha256(db_chunk_payload(database_chunks)) != chunk_generation_id:
        return None, "chunk_database_mirror_mismatch"
    return chunk_generation_id, None


def _hide_until_reapproved(paper: Paper) -> None:
    paper.public_index_generation_id = None
    paper.publication_status = "pending_review"
    paper.public_access_level = "hidden"
    paper.extraction_review_status = "needs_review"
    paper.extraction_reviewer_notes = None
    paper.extraction_reviewed_at = None
    paper.extraction_reviewed_by = None


def _quarantine_chunks(paper: Paper, chunks: list[Chunk], reason: str) -> None:
    paper.chunk_count = len(chunks)
    paper.chunk_extraction_generation_id = None
    paper.chunk_generation_id = None
    paper.corpus_eligibility_status = "needs_review"
    paper.corpus_exclusion_reason = f"generation_reconciliation:{reason}"
    for chunk in chunks:
        chunk.extraction_generation_id = None


def reconcile_generation_links(
    session: Session,
    *,
    project_root: Path | None = None,
    extraction_dir: Path | None = None,
    chunks_dir: Path | None = None,
    pdf_dir: Path | None = None,
    paper_ids: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Link legacy rows only when every source-generation artifact validates.

    This command never manufactures provenance from database rows. Missing or
    legacy manifests are quarantined and public delivery stays disabled until
    deterministic extraction/chunking, index rebuild, and human approval run.
    """

    root = (project_root or get_settings().project_root).resolve()
    extraction_root = (extraction_dir or root / "data" / "extracted_text").resolve()
    chunk_root = (chunks_dir or root / "data" / "chunks").resolve()
    pdf_root = (pdf_dir or root / "data" / "pdfs").resolve()
    allowed = set(paper_ids or [])
    papers = list(session.exec(select(Paper).order_by(Paper.paper_id)).all())
    if allowed:
        papers = [paper for paper in papers if paper.paper_id in allowed]
    if limit is not None:
        papers = papers[: max(limit, 0)]
    summary: dict[str, Any] = {
        "attempted": len(papers),
        "reconciled": 0,
        "already_current": 0,
        "quarantined": 0,
        "dry_run": dry_run,
        "reasons": {},
    }

    def record_reason(reason: str) -> None:
        reasons = summary["reasons"]
        reasons[reason] = int(reasons.get(reason, 0)) + 1

    for paper in papers:
        chunks = list(
            session.exec(
                select(Chunk).where(Chunk.paper_id == paper.paper_id).order_by(Chunk.chunk_index, Chunk.chunk_id)
            ).all()
        )
        extracted, extraction_error = _validate_extraction(
            paper,
            project_root=root,
            extraction_dir=extraction_root,
            pdf_dir=pdf_root,
        )
        if extracted is None:
            _quarantine_chunks(paper, chunks, str(extraction_error))
            paper.extraction_generation_id = None
            paper.extraction_input_pdf_sha256 = None
            paper.extraction_config_sha256 = None
            _hide_until_reapproved(paper)
            paper.updated_at = utc_now()
            session.add(paper)
            summary["quarantined"] += 1
            record_reason(str(extraction_error))
            continue

        extraction_generation_id = str(extracted["artifact_generation_id"])
        chunk_generation_id, chunk_error = _validate_chunks(
            paper,
            extracted,
            chunks,
            chunks_dir=chunk_root,
        )
        previous = (
            paper.extraction_generation_id,
            paper.extraction_input_pdf_sha256,
            paper.extraction_config_sha256,
            paper.chunk_extraction_generation_id,
            paper.chunk_generation_id,
        )
        paper.extraction_generation_id = extraction_generation_id
        paper.extraction_input_pdf_sha256 = str(extracted["input_pdf_sha256"])
        paper.extraction_config_sha256 = canonical_json_sha256(extracted["extraction_config"])
        if chunk_generation_id is None:
            _quarantine_chunks(paper, chunks, str(chunk_error))
            _hide_until_reapproved(paper)
            paper.updated_at = utc_now()
            session.add(paper)
            summary["quarantined"] += 1
            record_reason(str(chunk_error))
            continue

        current = (
            extraction_generation_id,
            str(extracted["input_pdf_sha256"]),
            canonical_json_sha256(extracted["extraction_config"]),
            extraction_generation_id,
            chunk_generation_id,
        )
        paper.chunk_count = len(chunks)
        paper.chunk_extraction_generation_id = extraction_generation_id
        paper.chunk_generation_id = chunk_generation_id
        for chunk in chunks:
            chunk.extraction_generation_id = extraction_generation_id
            session.add(chunk)
        if previous == current:
            summary["already_current"] += 1
        else:
            _hide_until_reapproved(paper)
            invalidate_generated_outputs_for_paper(
                session,
                paper.paper_id,
                reason="Generation links were reconciled; regenerate and reapprove source-grounded outputs.",
            )
            summary["reconciled"] += 1
        paper.updated_at = utc_now()
        session.add(paper)

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile source-to-chunk generation links fail closed.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--paper-id", action="append", default=None)
    reconcile.add_argument("--limit", type=int, default=None)
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--extraction-dir", type=Path, default=None)
    reconcile.add_argument("--chunks-dir", type=Path, default=None)
    reconcile.add_argument("--pdf-dir", type=Path, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        summary = reconcile_generation_links(
            session,
            extraction_dir=args.extraction_dir,
            chunks_dir=args.chunks_dir,
            pdf_dir=args.pdf_dir,
            paper_ids=args.paper_id,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
