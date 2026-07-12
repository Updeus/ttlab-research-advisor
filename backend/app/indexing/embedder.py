from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Chunk, Paper

FEATURE_HASHING_PROVIDER = "feature_hashing"
DENSE_PROVIDER = "dense"
DEFAULT_PROVIDER = FEATURE_HASHING_PROVIDER
DEFAULT_DIMENSIONS = 256
DEFAULT_INDEX_PATH = Path("data/indexes/feature_hashing_embeddings.json")
LEGACY_INDEX_PATH = Path("data/indexes/hashing_embeddings.json")
DENSE_INDEX_PATH = Path("data/indexes/dense_embeddings.json")
DEMO_INDEX_PATH = Path("data/indexes/demo/feature_hashing_embeddings.json")
MANIFEST_SCHEMA_VERSION = 1
NORMALIZATION = "l2"

DENSE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DENSE_MODEL_REVISION = "826711e54e001c83835913827a843d8dd0a1def9"
DENSE_MODEL_LICENSE = "Apache-2.0"
DENSE_DIMENSIONS = 384
DENSE_DEFAULT_DEVICE = "cpu"
DENSE_WINDOW_OVERLAP_TOKENS = 32

FEATURE_HASHING_ALGORITHM = "sha256-signed-token-hashing-v1"
FEATURE_HASHING_MODEL_DIGEST = hashlib.sha256(FEATURE_HASHING_ALGORITHM.encode("utf-8")).hexdigest()
EXCLUDED_INGESTION_STATUSES = {
    "excluded_source_mismatch",
    "source_mismatch",
    "excluded_permission_restricted",
    "permission_restricted",
}


class IndexIntegrityError(RuntimeError):
    """Raised when an index cannot be proven to match its corpus manifest."""


class DenseProviderUnavailable(RuntimeError):
    """Raised when the optional learned dense provider is not installed/acquired."""


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int
    model_name: str
    model_revision: str
    model_artifact_sha256: str
    normalization: str
    configuration: dict[str, Any]

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass
class HashingEmbeddingProvider:
    dimensions: int = DEFAULT_DIMENSIONS
    name: str = FEATURE_HASHING_PROVIDER
    model_name: str = FEATURE_HASHING_ALGORITHM
    model_revision: str = "1"
    model_artifact_sha256: str = FEATURE_HASHING_MODEL_DIGEST
    normalization: str = NORMALIZATION

    @property
    def configuration(self) -> dict[str, Any]:
        return {
            "algorithm": FEATURE_HASHING_ALGORITHM,
            "dimensions": self.dimensions,
            "normalization": self.normalization,
            "token_pattern": "[a-zA-Z0-9]+; length > 1; lowercase",
        }

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize(vector)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class SentenceTransformerEmbeddingProvider:
    """Pinned learned dense encoder loaded only from an explicit local snapshot.

    Long chunks are split using the model tokenizer. Every token is represented
    in at least one deterministic overlapping window; window vectors are mean
    pooled and L2-normalized into one vector per source chunk.
    """

    name = DENSE_PROVIDER
    dimensions = DENSE_DIMENSIONS
    model_name = DENSE_MODEL_NAME
    model_revision = DENSE_MODEL_REVISION
    normalization = NORMALIZATION

    def __init__(
        self,
        *,
        allow_model_download: bool = False,
        device: str = DENSE_DEFAULT_DEVICE,
        batch_size: int = 16,
        window_overlap_tokens: int = DENSE_WINDOW_OVERLAP_TOKENS,
    ) -> None:
        try:
            from huggingface_hub import snapshot_download
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise DenseProviderUnavailable(
                "Learned dense retrieval is unavailable. Install the pinned optional dependencies from "
                "backend/requirements-dense.txt, then explicitly acquire the pinned model with "
                "`python -m app.indexing.embedder acquire-dense-model`."
            ) from exc

        try:
            snapshot_path = Path(
                snapshot_download(
                    repo_id=self.model_name,
                    revision=self.model_revision,
                    local_files_only=not allow_model_download,
                )
            )
        except Exception as exc:
            action = "download" if allow_model_download else "locate in the local cache"
            raise DenseProviderUnavailable(
                f"Could not {action} pinned dense model {self.model_name}@{self.model_revision}: {exc}"
            ) from exc

        self.model_artifact_sha256 = hash_directory(snapshot_path)
        self.device = device
        self.batch_size = batch_size
        self._model = SentenceTransformer(str(snapshot_path), device=device, local_files_only=True)
        self._tokenizer = self._model.tokenizer
        model_max = int(getattr(self._model, "max_seq_length", 256) or 256)
        self.window_tokens = max(model_max - 2, 8)
        self.window_overlap_tokens = min(max(window_overlap_tokens, 0), self.window_tokens - 1)

    @property
    def configuration(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "normalization": self.normalization,
            "device": self.device,
            "batch_size": self.batch_size,
            "long_chunk_strategy": "token_windows_mean_pool",
            "window_tokens": self.window_tokens,
            "window_overlap_tokens": self.window_overlap_tokens,
            "window_pooling": "arithmetic_mean_then_l2",
            "license": DENSE_MODEL_LICENSE,
        }

    def _windows(self, text: str) -> list[str]:
        token_ids = self._tokenizer.encode(text, add_special_tokens=False, truncation=False)
        if not token_ids:
            return [""]
        step = self.window_tokens - self.window_overlap_tokens
        windows: list[str] = []
        for start in range(0, len(token_ids), step):
            ids = token_ids[start : start + self.window_tokens]
            windows.append(self._tokenizer.decode(ids, skip_special_tokens=True))
            if start + self.window_tokens >= len(token_ids):
                break
        return windows

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        flat_windows: list[str] = []
        owners: list[int] = []
        for owner, text in enumerate(texts):
            windows = self._windows(text)
            flat_windows.extend(windows)
            owners.extend([owner] * len(windows))
        encoded = self._model.encode(
            flat_windows,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        sums = [[0.0] * self.dimensions for _ in texts]
        counts = [0] * len(texts)
        for owner, vector in zip(owners, encoded, strict=True):
            values = [float(value) for value in vector]
            for index, value in enumerate(values):
                sums[owner][index] += value
            counts[owner] += 1
        return [normalize([value / max(counts[index], 1) for value in vector]) for index, vector in enumerate(sums)]


def canonical_provider_name(provider_name: str | None) -> str:
    normalized = (provider_name or DEFAULT_PROVIDER).strip().lower()
    aliases = {
        "hashing": FEATURE_HASHING_PROVIDER,
        "feature-hashing": FEATURE_HASHING_PROVIDER,
        "feature_hashing": FEATURE_HASHING_PROVIDER,
        "sentence_transformers": DENSE_PROVIDER,
        "sentence-transformers": DENSE_PROVIDER,
        "dense": DENSE_PROVIDER,
    }
    if normalized not in aliases:
        raise ValueError(f"Unknown embedding provider: {provider_name}")
    return aliases[normalized]


def default_index_path(provider_name: str) -> Path:
    return DENSE_INDEX_PATH if canonical_provider_name(provider_name) == DENSE_PROVIDER else DEFAULT_INDEX_PATH


def get_provider(
    provider_name: str = DEFAULT_PROVIDER,
    dimensions: int | None = None,
    *,
    allow_model_download: bool = False,
    device: str = DENSE_DEFAULT_DEVICE,
) -> EmbeddingProvider:
    canonical = canonical_provider_name(provider_name)
    if canonical == FEATURE_HASHING_PROVIDER:
        return HashingEmbeddingProvider(dimensions=dimensions or DEFAULT_DIMENSIONS)
    return _get_dense_provider(allow_model_download=allow_model_download, device=device)


@lru_cache(maxsize=4)
def _get_dense_provider(*, allow_model_download: bool, device: str) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(allow_model_download=allow_model_download, device=device)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 1]


def normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def manifest_path_for(index_path: Path) -> Path:
    return index_path.with_suffix(".manifest.json")


def current_code_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def eligible_chunks(session: Session) -> list[Chunk]:
    statement = select(Chunk, Paper).join(Paper, Paper.paper_id == Chunk.paper_id).order_by(
        Chunk.paper_id, Chunk.chunk_index, Chunk.chunk_id
    )
    pairs = list(session.exec(statement).all())
    # New snapshots use the reviewed eligibility field. A fallback is retained
    # only for pre-migration databases where no paper has yet been classified.
    has_explicit_eligibility = any(
        str(getattr(paper, "corpus_eligibility_status", "") or "").lower() == "eligible"
        for _chunk, paper in pairs
    )
    return [
        chunk
        for chunk, paper in pairs
        if (
            str(getattr(paper, "corpus_eligibility_status", "") or "").lower() == "eligible"
            if has_explicit_eligibility
            else not str(getattr(paper, "corpus_eligibility_status", "") or "").lower().startswith("excluded_")
            and not str(getattr(paper, "corpus_eligibility_status", "") or "").lower().startswith("ineligible_")
            and str(paper.ingestion_status or "").lower() not in EXCLUDED_INGESTION_STATUSES
        )
    ]


def corpus_descriptor(chunks: list[Chunk]) -> dict[str, Any]:
    ordered = [{"chunk_id": chunk.chunk_id, "source_hash": chunk.source_hash or ""} for chunk in chunks]
    snapshot_hash = sha256_bytes(canonical_json_bytes(ordered))
    return {
        "snapshot_id": f"corpus-{snapshot_hash[:16]}",
        "snapshot_hash": snapshot_hash,
        "eligible_paper_count": len({chunk.paper_id for chunk in chunks}),
        "eligible_chunk_count": len(chunks),
        "eligible_chunks": ordered,
    }


def build_embedding_records(chunks: list[Chunk], provider: EmbeddingProvider) -> list[dict[str, Any]]:
    now = utc_now_iso()
    embeddings = provider.embed_many([chunk.text for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise IndexIntegrityError("Embedding provider returned a different number of vectors than input chunks.")
    records: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if len(embedding) != provider.dimensions:
            raise IndexIntegrityError(
                f"Embedding for {chunk.chunk_id} has {len(embedding)} dimensions; expected {provider.dimensions}."
            )
        records.append(
            {
                "chunk_id": chunk.chunk_id,
                "paper_id": chunk.paper_id,
                "provider": provider.name,
                "dimensions": provider.dimensions,
                "source_hash": chunk.source_hash,
                "created_at": now,
                "embedding": embedding,
            }
        )
    return records


def build_index_payload(records: list[dict[str, Any]], provider: EmbeddingProvider, *, build_id: str) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "build_id": build_id,
        "provider": provider.name,
        "model_name": provider.model_name,
        "model_revision": provider.model_revision,
        "model_artifact_sha256": provider.model_artifact_sha256,
        "dimensions": provider.dimensions,
        "normalization": provider.normalization,
        "created_at": utc_now_iso(),
        "records": records,
    }


def build_manifest(
    *,
    index_payload: dict[str, Any],
    index_bytes: bytes,
    provider: EmbeddingProvider,
    corpus: dict[str, Any],
    indexed_chunks: list[Chunk],
    output_path: Path,
    index_role: str,
) -> dict[str, Any]:
    indexed_descriptor = [
        {"chunk_id": chunk.chunk_id, "source_hash": chunk.source_hash or ""} for chunk in indexed_chunks
    ]
    config = {
        "provider": provider.name,
        "model_name": provider.model_name,
        "model_revision": provider.model_revision,
        "model_artifact_sha256": provider.model_artifact_sha256,
        **provider.configuration,
    }
    complete = indexed_descriptor == corpus["eligible_chunks"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_type": "ttlab_vector_index",
        "build_id": index_payload["build_id"],
        "created_at": index_payload["created_at"],
        "code_commit": current_code_commit(),
        "index_role": index_role,
        "corpus": corpus,
        "index": {
            "path": str(output_path),
            "sha256": sha256_bytes(index_bytes),
            "provider": provider.name,
            "model_name": provider.model_name,
            "model_revision": provider.model_revision,
            "model_artifact_sha256": provider.model_artifact_sha256,
            "dimensions": provider.dimensions,
            "normalization": provider.normalization,
            "indexed_chunk_count": len(indexed_chunks),
            "indexed_chunks": indexed_descriptor,
            "completeness_status": "complete" if complete else "partial",
        },
        "configuration": config,
        "configuration_hash": sha256_bytes(canonical_json_bytes(config)),
    }


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write_bytes(path, previous)


def write_index_and_manifest(index_path: Path, index_bytes: bytes, manifest: dict[str, Any]) -> None:
    manifest_path = manifest_path_for(index_path)
    previous_index = index_path.read_bytes() if index_path.exists() else None
    previous_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
    try:
        atomic_write_bytes(index_path, index_bytes)
        atomic_write_bytes(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    except Exception:
        _restore_file(index_path, previous_index)
        _restore_file(manifest_path, previous_manifest)
        raise


def status_providers(status: str | None) -> set[str]:
    if not status or not status.startswith("indexed:"):
        return set()
    providers: set[str] = set()
    for raw in status.removeprefix("indexed:").split(","):
        try:
            providers.add(canonical_provider_name(raw))
        except ValueError:
            continue
    return providers


def format_embedding_status(providers: set[str]) -> str:
    return f"indexed:{','.join(sorted(providers))}" if providers else "not_indexed"


def update_embedding_statuses(
    session: Session,
    *,
    provider_name: str,
    all_chunks: list[Chunk],
    indexed_chunks: list[Chunk],
) -> None:
    canonical = canonical_provider_name(provider_name)
    indexed_ids = {chunk.chunk_id for chunk in indexed_chunks}
    for chunk in all_chunks:
        providers = status_providers(chunk.embedding_status)
        providers.discard(canonical)
        if chunk.chunk_id in indexed_ids:
            providers.add(canonical)
        chunk.embedding_status = format_embedding_status(providers)
        session.add(chunk)


def index_chunks(
    session: Session,
    *,
    provider_name: str = DEFAULT_PROVIDER,
    limit: int | None = None,
    output_path: Path | None = None,
    allow_partial: bool = False,
    update_db_status: bool = True,
    index_role: str = "authoritative",
    allow_model_download: bool = False,
    device: str = DENSE_DEFAULT_DEVICE,
    provider_override: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    canonical = canonical_provider_name(provider_name)
    resolved_output = output_path or default_index_path(canonical)
    canonical_output = default_index_path(canonical)
    if limit is not None and (not allow_partial or resolved_output.resolve() == canonical_output.resolve()):
        raise ValueError(
            "A bounded rebuild cannot overwrite an authoritative index. Use a separate output path with allow_partial=True."
        )
    if allow_partial and update_db_status:
        raise ValueError("Partial/demo indexes cannot update authoritative database embedding statuses.")

    provider = provider_override or get_provider(
        canonical,
        allow_model_download=allow_model_download,
        device=device,
    )
    all_eligible = eligible_chunks(session)
    selected = all_eligible[:limit] if limit is not None else all_eligible
    corpus = corpus_descriptor(all_eligible)
    records = build_embedding_records(selected, provider)
    build_id = f"{provider.name}-{utc_now_iso()}-{corpus['snapshot_hash'][:12]}"
    payload = build_index_payload(records, provider, build_id=build_id)
    index_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    manifest = build_manifest(
        index_payload=payload,
        index_bytes=index_bytes,
        provider=provider,
        corpus=corpus,
        indexed_chunks=selected,
        output_path=resolved_output,
        index_role=index_role,
    )

    old_index = resolved_output.read_bytes() if resolved_output.exists() else None
    manifest_path = manifest_path_for(resolved_output)
    old_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
    write_index_and_manifest(resolved_output, index_bytes, manifest)
    try:
        if update_db_status:
            all_db_chunks = list(session.exec(select(Chunk)).all())
            update_embedding_statuses(
                session,
                provider_name=provider.name,
                all_chunks=all_db_chunks,
                indexed_chunks=selected,
            )
            session.commit()
    except Exception:
        session.rollback()
        _restore_file(resolved_output, old_index)
        _restore_file(manifest_path, old_manifest)
        raise

    report = validate_index_manifest(
        session if update_db_status else None,
        index_path=resolved_output,
        provider_name=provider.name,
        require_complete=not allow_partial,
        check_db_status=update_db_status,
    )
    if not report["valid"]:
        raise IndexIntegrityError("Index validation failed after build: " + "; ".join(report["errors"]))
    return {
        "provider": provider.name,
        "model_name": provider.model_name,
        "model_revision": provider.model_revision,
        "model_artifact_sha256": provider.model_artifact_sha256,
        "dimensions": provider.dimensions,
        "normalization": provider.normalization,
        "indexed_chunks": len(records),
        "eligible_chunks": len(all_eligible),
        "completeness_status": manifest["index"]["completeness_status"],
        "corpus_snapshot_id": corpus["snapshot_id"],
        "corpus_snapshot_hash": corpus["snapshot_hash"],
        "index_path": str(resolved_output),
        "manifest_path": str(manifest_path),
        "index_sha256": manifest["index"]["sha256"],
        "configuration_hash": manifest["configuration_hash"],
        "index_status": "ready" if manifest["index"]["completeness_status"] == "complete" else "partial",
    }


def load_embedding_index(index_path: Path = DEFAULT_INDEX_PATH) -> dict[str, Any] | None:
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))


def load_manifest(index_path: Path = DEFAULT_INDEX_PATH) -> dict[str, Any] | None:
    path = manifest_path_for(index_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_index_manifest(
    session: Session | None,
    *,
    index_path: Path = DEFAULT_INDEX_PATH,
    provider_name: str = DEFAULT_PROVIDER,
    require_complete: bool = True,
    check_db_status: bool = True,
) -> dict[str, Any]:
    canonical = canonical_provider_name(provider_name)
    errors: list[str] = []
    index_exists = index_path.exists()
    if not index_exists:
        errors.append(f"Index file is missing: {index_path}")
    manifest_path = manifest_path_for(index_path)
    manifest_exists = manifest_path.exists()
    if not manifest_exists:
        errors.append(f"Index manifest is missing: {manifest_path}")
    if errors:
        return {
            "valid": False,
            "status": "missing" if not index_exists and not manifest_exists else "invalid",
            "errors": errors,
            "index_path": str(index_path),
            "manifest_path": str(manifest_path),
        }
    try:
        payload = load_embedding_index(index_path) or {}
        manifest = load_manifest(index_path) or {}
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "status": "invalid", "errors": [f"Could not parse index artifacts: {exc}"], "index_path": str(index_path), "manifest_path": str(manifest_path)}

    index_meta = manifest.get("index") or {}
    corpus = manifest.get("corpus") or {}
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("Unsupported or missing manifest schema_version.")
    if payload.get("build_id") != manifest.get("build_id"):
        errors.append("Index build_id does not match manifest build_id.")
    if payload.get("provider") != canonical or index_meta.get("provider") != canonical:
        errors.append(f"Index provider does not match expected provider {canonical}.")
    for field_name in ("model_name", "model_revision", "model_artifact_sha256", "dimensions", "normalization"):
        if payload.get(field_name) != index_meta.get(field_name):
            errors.append(f"Index {field_name} does not match manifest.")
    actual_index_hash = sha256_file(index_path)
    if index_meta.get("sha256") != actual_index_hash:
        errors.append("Index file hash does not match manifest.")
    indexed_descriptor = [
        {"chunk_id": str(record.get("chunk_id") or ""), "source_hash": str(record.get("source_hash") or "")}
        for record in payload.get("records", [])
    ]
    if indexed_descriptor != index_meta.get("indexed_chunks"):
        errors.append("Ordered index records do not match manifest indexed_chunks.")
    if len(indexed_descriptor) != len({item["chunk_id"] for item in indexed_descriptor}):
        errors.append("Index contains duplicate chunk IDs.")
    if int(index_meta.get("indexed_chunk_count") or -1) != len(indexed_descriptor):
        errors.append("Manifest indexed_chunk_count is incorrect.")
    dimensions = int(index_meta.get("dimensions") or 0)
    if any(len(record.get("embedding") or []) != dimensions for record in payload.get("records", [])):
        errors.append("At least one vector has the wrong dimension.")
    for record in payload.get("records", []):
        vector = record.get("embedding") or []
        if any(not math.isfinite(float(value)) for value in vector):
            errors.append("At least one vector contains a non-finite value.")
            break
        magnitude = math.sqrt(sum(float(value) * float(value) for value in vector))
        if magnitude and not math.isclose(magnitude, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            errors.append("At least one nonzero vector is not L2-normalized.")
            break
    if require_complete and index_meta.get("completeness_status") != "complete":
        errors.append("Index manifest is partial; an authoritative complete index is required.")
    if index_meta.get("completeness_status") == "complete" and indexed_descriptor != corpus.get("eligible_chunks"):
        errors.append("Complete index records do not match the manifest corpus descriptor.")
    configuration = manifest.get("configuration") or {}
    if manifest.get("configuration_hash") != sha256_bytes(canonical_json_bytes(configuration)):
        errors.append("Manifest configuration_hash is incorrect.")

    current_corpus: dict[str, Any] | None = None
    if session is not None:
        current_chunks = eligible_chunks(session)
        current_corpus = corpus_descriptor(current_chunks)
        if current_corpus["snapshot_hash"] != corpus.get("snapshot_hash"):
            errors.append("Current eligible corpus snapshot does not match the index manifest.")
        if current_corpus["eligible_chunks"] != corpus.get("eligible_chunks"):
            errors.append("Current ordered chunk IDs/source hashes do not match the index manifest.")
        if current_corpus["eligible_paper_count"] != int(corpus.get("eligible_paper_count") or -1):
            errors.append("Current eligible paper count does not match the index manifest.")
        if check_db_status:
            indexed_ids = {item["chunk_id"] for item in indexed_descriptor}
            stale = [
                chunk.chunk_id
                for chunk in session.exec(select(Chunk)).all()
                if (canonical in status_providers(chunk.embedding_status)) != (chunk.chunk_id in indexed_ids)
            ]
            if stale:
                errors.append(f"Database embedding statuses disagree with the manifest for {len(stale)} chunk(s).")

    return {
        "valid": not errors,
        "status": "ready" if not errors else "invalid",
        "errors": errors,
        "index_path": str(index_path),
        "manifest_path": str(manifest_path),
        "provider": index_meta.get("provider", canonical),
        "model_name": index_meta.get("model_name"),
        "model_revision": index_meta.get("model_revision"),
        "model_artifact_sha256": index_meta.get("model_artifact_sha256"),
        "dimensions": dimensions,
        "normalization": index_meta.get("normalization"),
        "indexed_chunks": len(indexed_descriptor),
        "eligible_chunks": int(corpus.get("eligible_chunk_count") or 0),
        "eligible_papers": int(corpus.get("eligible_paper_count") or 0),
        "completeness_status": index_meta.get("completeness_status"),
        "corpus_snapshot_id": corpus.get("snapshot_id"),
        "corpus_snapshot_hash": corpus.get("snapshot_hash"),
        "configuration_hash": manifest.get("configuration_hash"),
        "index_sha256": index_meta.get("sha256"),
        "created_at": manifest.get("created_at"),
        "code_commit": manifest.get("code_commit"),
        "current_corpus_snapshot_hash": current_corpus.get("snapshot_hash") if current_corpus else None,
    }


def load_validated_index(
    session: Session,
    *,
    index_path: Path,
    provider_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = validate_index_manifest(
        session,
        index_path=index_path,
        provider_name=provider_name,
        require_complete=True,
        check_db_status=True,
    )
    if not report["valid"]:
        raise IndexIntegrityError("; ".join(report["errors"]))
    payload = load_embedding_index(index_path)
    if payload is None:
        raise IndexIntegrityError(f"Index disappeared after validation: {index_path}")
    return payload, report


def index_diagnostics(
    session: Session | None = None,
    index_path: Path = DEFAULT_INDEX_PATH,
    provider_name: str = DEFAULT_PROVIDER,
) -> dict[str, Any]:
    report = validate_index_manifest(
        session,
        index_path=index_path,
        provider_name=provider_name,
        require_complete=True,
        check_db_status=session is not None,
    )
    indexed_chunks = int(report.get("indexed_chunks") or 0)
    return {
        **report,
        "indexed_chunks": indexed_chunks,
        "eligible_chunks": int(report.get("eligible_chunks") or 0),
        "completeness_status": report.get("completeness_status") or "missing",
        "semantic_indexed_chunks": indexed_chunks,  # legacy response field
        "embedding_provider": report.get("provider", canonical_provider_name(provider_name)),
        "embedding_dimensions": report.get("dimensions") or (DENSE_DIMENSIONS if canonical_provider_name(provider_name) == DENSE_PROVIDER else DEFAULT_DIMENSIONS),
        "index_status": report["status"],
        "last_indexed_at": report.get("created_at"),
    }


def validate_present_authoritative_indexes(session: Session) -> dict[str, dict[str, Any]]:
    """Fail startup when an index is present but cannot prove readiness.

    A genuinely missing optional index is reported and may be handled by the
    documented fallback. A present legacy, partial, stale, or corrupted index
    is never treated as usable.
    """

    reports = {
        FEATURE_HASHING_PROVIDER: index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER),
        DENSE_PROVIDER: index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER),
    }
    invalid = {
        provider: report["errors"]
        for provider, report in reports.items()
        if report["status"] == "invalid"
    }
    if invalid:
        details = "; ".join(f"{provider}: {', '.join(errors)}" for provider, errors in invalid.items())
        raise IndexIntegrityError(f"Authoritative index startup validation failed: {details}")
    return reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and validate versioned local vector indexes.")
    subparsers = parser.add_subparsers(dest="command")
    index = subparsers.add_parser("index")
    index.add_argument("--provider", choices=["feature_hashing", "hashing", "dense"], default=DEFAULT_PROVIDER)
    index.add_argument("--limit", type=int, default=None)
    index.add_argument("--out", default=None)
    index.add_argument("--allow-partial", action="store_true")
    index.add_argument("--no-status-update", action="store_true")
    index.add_argument("--allow-model-download", action="store_true")
    index.add_argument("--device", choices=["cpu", "cuda"], default=DENSE_DEFAULT_DEVICE)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--provider", choices=["feature_hashing", "hashing", "dense"], default=DEFAULT_PROVIDER)
    validate.add_argument("--index", default=None)
    acquire = subparsers.add_parser("acquire-dense-model")
    acquire.add_argument("--device", choices=["cpu", "cuda"], default=DENSE_DEFAULT_DEVICE)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "acquire-dense-model":
        provider = get_provider(DENSE_PROVIDER, allow_model_download=True, device=args.device)
        print(
            f"provider={provider.name} model={provider.model_name} revision={provider.model_revision} "
            f"artifact_sha256={provider.model_artifact_sha256} dimensions={provider.dimensions} device={args.device}"
        )
        return
    if args.command == "validate":
        create_db_and_tables()
        provider_name = canonical_provider_name(args.provider)
        index_path = Path(args.index) if args.index else default_index_path(provider_name)
        with Session(engine) as session:
            report = validate_index_manifest(session, index_path=index_path, provider_name=provider_name)
        print(json.dumps(report, indent=2))
        if not report["valid"]:
            raise SystemExit(1)
        return
    if args.command != "index":
        build_parser().print_help()
        return
    create_db_and_tables()
    provider_name = canonical_provider_name(args.provider)
    output_path = Path(args.out) if args.out else default_index_path(provider_name)
    with Session(engine) as session:
        result = index_chunks(
            session,
            provider_name=provider_name,
            limit=args.limit,
            output_path=output_path,
            allow_partial=args.allow_partial,
            update_db_status=not args.no_status_update,
            index_role="bounded_demo" if args.allow_partial else "authoritative",
            allow_model_download=args.allow_model_download,
            device=args.device,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
