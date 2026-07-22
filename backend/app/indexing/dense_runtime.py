from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Literal

from app.indexing.embedder import DENSE_PROVIDER, get_provider

DenseRuntimeState = Literal["idle", "warming", "ready", "unavailable"]

_lock = threading.Lock()
_state: DenseRuntimeState = "idle"
_started_at: str | None = None
_ready_at: str | None = None
_elapsed_seconds: float | None = None


def dense_runtime_diagnostics() -> dict[str, object]:
    with _lock:
        return {
            "state": _state,
            "started_at": _started_at,
            "ready_at": _ready_at,
            "elapsed_seconds": _elapsed_seconds,
        }


def warm_dense_provider() -> None:
    global _state, _started_at, _ready_at, _elapsed_seconds
    with _lock:
        if _state == "ready":
            return
        _state = "warming"
        _started_at = datetime.now(UTC).isoformat()
        _ready_at = None
        _elapsed_seconds = None
    started = time.monotonic()
    try:
        provider = get_provider(DENSE_PROVIDER)
        provider.embed("TTLAB dense semantic retrieval warmup")
    except Exception:
        with _lock:
            _state = "unavailable"
            _elapsed_seconds = round(time.monotonic() - started, 3)
        return
    with _lock:
        _state = "ready"
        _ready_at = datetime.now(UTC).isoformat()
        _elapsed_seconds = round(time.monotonic() - started, 3)
