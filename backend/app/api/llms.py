from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.public import redact_local_paths
from app.config import Settings, get_settings
from app.intelligence.local_llms import (
    UNVALIDATED_MODEL_WARNING,
    local_llm_status,
    read_latest_benchmark,
)

router = APIRouter(prefix="/api/llms", tags=["llms"])


@router.get("/status")
def generation_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    provider = settings.default_llm_provider
    allowed = {value.strip().lower() for value in settings.allowed_llm_providers}
    if provider == "offline_extractive" and "ollama" in allowed:
        # Ask can still default to extractive composition while the structured
        # Idea Generator uses the only configured local structured provider.
        provider = "ollama"
    if provider == "vertex_gemini":
        return {
            "runtime_profile": settings.runtime_profile,
            "provider": provider,
            "display_name": "Google Gemini on Vertex AI",
            "configured": bool(settings.google_cloud_project),
            "location": settings.google_cloud_location,
            "model": settings.gemini_default_model,
            "model_selection_enabled": settings.public_provider_selection,
            "external_processing": True,
            "privacy_notice": (
                "Questions or conversation messages and retrieved TTLAB passages are processed by Google Vertex AI. "
                "No Google Search, URL context, or external grounding tools are enabled."
            ),
        }
    return {
        "runtime_profile": settings.runtime_profile,
        "provider": provider,
        "display_name": "Local Ollama" if provider == "ollama" else "Offline extractive",
        "configured": True,
        "model": (
            settings.ollama_default_model if provider == "ollama" else "sentence-overlap-v1"
        ),
        "model_selection_enabled": settings.public_provider_selection,
        "external_processing": False,
        "privacy_notice": "Generation stays on the configured local runtime.",
    }


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
            "No installed local Ollama model is currently usable; Ask TTLAB defaults to the offline extractive provider."
            if payload.get("model_policy") == "all_installed_local_models"
            else "No digest-verified local generation model is currently usable; Ask TTLAB defaults to the offline extractive provider.",
        )
    elif payload.get("model_policy") == "all_installed_local_models":
        public_warnings.insert(
            0,
            "Local demo policy allows every model installed in Ollama; these models are not required to have configured digest pins.",
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
