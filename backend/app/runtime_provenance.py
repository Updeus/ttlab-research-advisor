"""Shared, source-derived provenance for generated intelligence records."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from sqlmodel import Session

from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    corpus_descriptor,
    eligible_chunks,
    index_diagnostics,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.indexing.keyword_search import keyword_index_metadata

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_SCHEMA_VERSION = 1


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_runtime_provenance(
    session: Session,
    *,
    record_type: str,
    generation_config: Mapping[str, Any],
    provider: str,
    model: str,
    generated_at: datetime | str,
    retrieval_mode: str | None,
    source_chunk_ids: Sequence[str],
    generation_metadata: Mapping[str, Any] | None = None,
    retrieval_metadata: Mapping[str, Any] | None = None,
    corpus_scope: Literal["public", "technical"],
) -> dict[str, Any]:
    chunks = eligible_chunks(session, public_only=corpus_scope == "public")
    corpus = corpus_descriptor(session, chunks)
    source_ids = sorted({str(value) for value in source_chunk_ids if str(value)})
    effective_by_id = {item["chunk_id"]: item["source_hash"] for item in corpus["eligible_chunks"]}
    source_hashes = {chunk_id: effective_by_id.get(chunk_id, "") for chunk_id in source_ids}
    metadata = dict(generation_metadata or {})
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "record_type": record_type,
        "generated_at": generated_at.isoformat() if isinstance(generated_at, datetime) else str(generated_at),
        "code_identity": code_identity(),
        "corpus_identity": {
            "scope": corpus_scope,
            "snapshot_id": corpus["snapshot_id"],
            "snapshot_hash": corpus["snapshot_hash"],
            "eligible_chunk_count": corpus["eligible_chunk_count"],
            "eligible_paper_count": corpus["eligible_paper_count"],
        },
        "source_identity": {
            "chunk_ids": source_ids,
            "chunk_descriptor_sha256": canonical_hash(source_hashes),
        },
        "retrieval_identity": retrieval_identity(
            session,
            retrieval_mode=retrieval_mode,
            retrieval_metadata=retrieval_metadata or {},
            corpus_scope=corpus_scope,
        ),
        "generation_identity": {
            "configuration_sha256": canonical_hash(dict(generation_config)),
            "provider": provider,
            "model": model,
            "immutable_model_identity": immutable_model_identity(provider, model),
            "prompt_template_version": metadata.get("prompt_template_version"),
            "prompt_sha256": metadata.get("prompt_sha256"),
            "generation_config_sha256": metadata.get("generation_config_sha256"),
            "provider_resolution": sanitize_provider_resolution(metadata.get("provider_resolution")),
        },
    }


def immutable_model_identity(provider: str, model: str) -> bool:
    if provider == "ollama":
        return "@sha256:" in model
    return bool(model and (model.endswith("-v1") or model.endswith("-v2") or "@sha256:" in model))


def sanitize_provider_resolution(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = {
        "requested_provider",
        "configured_provider",
        "effective_provider",
        "requested_model",
        "configured_model",
        "effective_model",
        "configured_model_digest",
        "model_digest",
        "preflight_model_digest",
        "postflight_model_digest",
        "generation_time_digest_verified",
        "tag_stable_across_generation",
        "fallback_used",
        "fallback_reason",
        "fallback_exception_class",
        "region",
    }
    return {key: value.get(key) for key in sorted(allowed) if key in value}


def retrieval_identity(
    session: Session,
    *,
    retrieval_mode: str | None,
    retrieval_metadata: Mapping[str, Any],
    corpus_scope: Literal["public", "technical"],
) -> dict[str, Any]:
    if retrieval_mode is None:
        return {
            "mode": "direct_database_chunks",
            "scope": corpus_scope,
            "strategy": "ordered_source_chunk_selection",
            "indexes": [],
        }
    reports: list[dict[str, Any]] = []
    public_projection = corpus_scope == "public"
    if retrieval_mode in {"keyword", "hybrid"}:
        keyword = keyword_diagnostics(session)
        metadata = keyword_index_metadata(session) or {}
        reports.append(
            {
                "kind": "keyword",
                "provider": keyword.get("provider"),
                "status": keyword.get("status"),
                "completeness_status": keyword.get("completeness_status"),
                "configuration_sha256": metadata.get("configuration_hash"),
                "corpus_snapshot_hash": None
                if public_projection
                else keyword.get("stored_corpus_snapshot_hash"),
            }
        )
    if retrieval_mode in {"feature_hashing", "hybrid"}:
        reports.append(
            _vector_identity(
                index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER),
                disclose_corpus_identity=not public_projection,
            )
        )
    if retrieval_mode == "dense" or (
        retrieval_mode == "hybrid" and retrieval_metadata.get("vector_provider") == DENSE_PROVIDER
    ):
        reports.append(
            _vector_identity(
                index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER),
                disclose_corpus_identity=not public_projection,
            )
        )
    return {
        "mode": retrieval_mode,
        "scope": corpus_scope,
        "strategy": retrieval_metadata.get("retrieval_strategy"),
        "retriever_configuration_sha256": canonical_hash(retrieval_metadata.get("retriever_config") or {}),
        "indexes": reports,
    }


def _vector_identity(
    report: Mapping[str, Any],
    *,
    disclose_corpus_identity: bool = True,
) -> dict[str, Any]:
    return {
        "kind": str(report.get("embedding_provider") or report.get("provider") or "vector"),
        "provider": report.get("embedding_provider") or report.get("provider"),
        "status": report.get("status") or report.get("index_status"),
        "completeness_status": report.get("completeness_status"),
        "model_name": report.get("model_name"),
        "model_revision": report.get("model_revision"),
        "model_artifact_sha256": report.get("model_artifact_sha256"),
        "configuration_sha256": report.get("configuration_hash"),
        "index_sha256": report.get("index_sha256") if disclose_corpus_identity else None,
        "corpus_snapshot_hash": report.get("corpus_snapshot_hash") if disclose_corpus_identity else None,
    }


def code_identity() -> dict[str, Any]:
    try:
        head_commit = _git("rev-parse", "HEAD")
        head_tree = _git("rev-parse", "HEAD:backend/app")
        status = _git("status", "--porcelain=v1", "--untracked-files=all", "--", "backend/app")
        diff = _git("diff", "--binary", "HEAD", "--", "backend/app")
        untracked = _git("ls-files", "--others", "--exclude-standard", "--", "backend/app")
        fingerprint = hashlib.sha256(diff.encode("utf-8"))
        for relative in sorted(line for line in untracked.splitlines() if line):
            path = (REPO_ROOT / relative).resolve()
            if path.is_file() and REPO_ROOT in path.parents:
                fingerprint.update(relative.encode("utf-8"))
                fingerprint.update(path.read_bytes())
        dirty = bool(status.strip())
        return {
            "status": "dirty_worktree" if dirty else "clean_commit",
            "git_commit": None if dirty else head_commit,
            "git_head_commit": head_commit,
            "git_tree": None if dirty else head_tree,
            "git_head_tree": head_tree,
            "working_tree_dirty": dirty,
            "working_tree_fingerprint_sha256": fingerprint.hexdigest() if dirty else None,
            "scope": "backend/app",
        }
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {
            "status": "unresolvable",
            "git_commit": None,
            "git_head_commit": None,
            "git_tree": None,
            "git_head_tree": None,
            "working_tree_dirty": None,
            "working_tree_fingerprint_sha256": None,
            "scope": "backend/app",
        }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
