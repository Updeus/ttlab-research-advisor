from __future__ import annotations

from fastapi import APIRouter

from app.api.public import redact_local_paths
from app.intelligence.local_llms import (
    UNVALIDATED_MODEL_WARNING,
    local_llm_status,
    read_latest_benchmark,
)

router = APIRouter(prefix="/api/llms", tags=["llms"])


@router.get("/local")
def local_llms() -> dict[str, object]:
    payload = dict(local_llm_status())
    # The public UI needs availability and model metadata, not the internal
    # provider address or socket/HTTP exception details.
    payload.pop("base_url", None)
    public_warnings = [
        UNVALIDATED_MODEL_WARNING,
        (
            "Installed-tag digest checks establish configuration readiness only. Ask TTLAB checks the tag before "
            "and after each generation; without a response-reported digest, output remains attributed to the "
            "mutable tag and is not claimed to have reproducible generation-time model identity."
        ),
    ]
    if not payload.get("generation_available"):
        public_warnings.insert(
            0,
            "No digest-verified local generation model is currently usable; Ask TTLAB defaults to the offline extractive provider.",
        )
    payload["warnings"] = public_warnings
    return redact_local_paths(payload)


@router.get("/benchmark/latest")
def latest_llm_benchmark() -> dict[str, object]:
    payload = read_latest_benchmark()
    if payload is None:
        payload = {
            "status": "not_run",
            "results": [],
            "summary": {},
            "warnings": ["No local Ollama benchmark has been run yet."],
        }
    return redact_local_paths(payload)
