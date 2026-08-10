from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.config import Settings, get_settings


class ObjectStore(Protocol):
    def read_bytes(self, uri: str) -> bytes: ...
    def write_bytes(self, uri: str, payload: bytes, *, content_type: str | None = None) -> None: ...
    def exists(self, uri: str) -> bool: ...


class LocalFileStore:
    def read_bytes(self, uri: str) -> bytes:
        return local_path(uri).read_bytes()

    def write_bytes(self, uri: str, payload: bytes, *, content_type: str | None = None) -> None:
        path = local_path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def exists(self, uri: str) -> bool:
        return local_path(uri).is_file()


class GCSObjectStore:
    def __init__(self) -> None:
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover - GCP image dependency
            raise RuntimeError("google-cloud-storage is required for GCS storage") from exc
        self.client = storage.Client()

    def read_bytes(self, uri: str) -> bytes:
        bucket, key = parse_gs_uri(uri)
        return self.client.bucket(bucket).blob(key).download_as_bytes()

    def write_bytes(self, uri: str, payload: bytes, *, content_type: str | None = None) -> None:
        bucket, key = parse_gs_uri(uri)
        self.client.bucket(bucket).blob(key).upload_from_string(payload, content_type=content_type)

    def exists(self, uri: str) -> bool:
        bucket, key = parse_gs_uri(uri)
        return self.client.bucket(bucket).blob(key).exists()


def object_store(settings: Settings | None = None) -> ObjectStore:
    runtime = settings or get_settings()
    return GCSObjectStore() if runtime.storage_backend == "gcs" else LocalFileStore()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("Expected a gs:// URI")
    bucket, separator, key = uri[5:].partition("/")
    if not separator or not bucket or not key or ".." in PurePosixPath(key).parts:
        raise ValueError("Invalid GCS object URI")
    return bucket, key


def local_path(uri: str) -> Path:
    value = uri.removeprefix("file://")
    return Path(value)


_INDEX_REFRESH_LOCK = threading.Lock()
_INDEX_LAST_CHECK: dict[str, float] = {}


def refresh_gcs_vector_generation(index_path: Path, settings: Settings | None = None) -> bool:
    """TTL-poll GCS and publish a verified pointer only after its generation files."""

    runtime = settings or get_settings()
    if not runtime.is_gcp or runtime.storage_backend != "gcs" or not runtime.gcs_bucket:
        return False
    now = time.monotonic()
    key = index_path.name
    with _INDEX_REFRESH_LOCK:
        if now - _INDEX_LAST_CHECK.get(key, 0.0) < runtime.gcs_index_refresh_seconds:
            return False
        _INDEX_LAST_CHECK[key] = now
        store = object_store(runtime)
        prefix = runtime.gcs_index_prefix.strip("/")
        pointer_uri = f"gs://{runtime.gcs_bucket}/{prefix}/{index_path.name}.current.json"
        if not store.exists(pointer_uri):
            return False
        pointer_bytes = store.read_bytes(pointer_uri)
        pointer = json.loads(pointer_bytes)
        if pointer.get("pointer_type") != "ttlab_vector_index_current_generation":
            raise ValueError("GCS vector pointer has an unsupported type")
        index_relative = safe_relative(str(pointer.get("index_path") or ""))
        manifest_relative = safe_relative(str(pointer.get("manifest_path") or ""))
        remote_base = f"gs://{runtime.gcs_bucket}/{prefix}/"
        index_bytes = store.read_bytes(remote_base + index_relative.as_posix())
        manifest_bytes = store.read_bytes(remote_base + manifest_relative.as_posix())
        verify_sha256(index_bytes, str(pointer.get("index_sha256") or ""), "index")
        verify_sha256(manifest_bytes, str(pointer.get("manifest_sha256") or ""), "manifest")
        # The application loader performs the final manifest/corpus validation.
        destination_root = index_path.parent
        atomic_write(destination_root / index_relative, index_bytes)
        atomic_write(destination_root / manifest_relative, manifest_bytes)
        local_pointer = destination_root / f"{index_path.name}.current.json"
        if local_pointer.is_file() and local_pointer.read_bytes() == pointer_bytes:
            return False
        atomic_write(local_pointer, pointer_bytes)
        return True


def publish_gcs_vector_generation(
    index_path: Path,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Publish immutable files first and advance the GCS pointer last."""

    runtime = settings or get_settings()
    if runtime.storage_backend != "gcs" or not runtime.gcs_bucket:
        raise ValueError("GCS vector publication requires a configured bucket")
    pointer_path = index_path.parent / f"{index_path.name}.current.json"
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes)
    if pointer.get("pointer_type") != "ttlab_vector_index_current_generation":
        raise ValueError("Local vector pointer has an unsupported type")
    index_relative = safe_relative(str(pointer.get("index_path") or ""))
    manifest_relative = safe_relative(str(pointer.get("manifest_path") or ""))
    index_bytes = (index_path.parent / index_relative).read_bytes()
    manifest_bytes = (index_path.parent / manifest_relative).read_bytes()
    verify_sha256(index_bytes, str(pointer.get("index_sha256") or ""), "index")
    verify_sha256(manifest_bytes, str(pointer.get("manifest_sha256") or ""), "manifest")
    store = object_store(runtime)
    prefix = runtime.gcs_index_prefix.strip("/")
    remote_base = f"gs://{runtime.gcs_bucket}/{prefix}/"
    index_uri = remote_base + index_relative.as_posix()
    manifest_uri = remote_base + manifest_relative.as_posix()
    pointer_uri = remote_base + f"{index_path.name}.current.json"
    store.write_bytes(index_uri, index_bytes, content_type="application/json")
    store.write_bytes(manifest_uri, manifest_bytes, content_type="application/json")
    store.write_bytes(pointer_uri, pointer_bytes, content_type="application/json")
    return {
        "index_uri": index_uri,
        "manifest_uri": manifest_uri,
        "pointer_uri": pointer_uri,
        "build_id": str(pointer.get("build_id") or ""),
    }


def safe_relative(value: str) -> Path:
    posix = PurePosixPath(value)
    if not value or posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Vector pointer contains an unsafe path")
    return Path(*posix.parts)


def verify_sha256(payload: bytes, expected: str, label: str) -> None:
    if len(expected) != 64 or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"GCS vector {label} checksum mismatch")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
