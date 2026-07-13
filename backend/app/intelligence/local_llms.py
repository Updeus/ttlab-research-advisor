from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

BENCHMARK_RESULTS_PATH = Path("data/evaluation/ollama_benchmark_results.json")

CONFIGURED_MODEL_NAMES = (
    "qwen3:4b-instruct-2507-q4_K_M",
    "gemma3:4b-it-q4_K_M",
    "phi3.5:3.8b-mini-instruct-q4_K_M",
    "ministral-3:3b-instruct-2512-q4_K_M",
    "llama3.2:3b",
    "phi3:mini",
    "smollm2:1.7b",
    "smollm2:360m",
    "qwen2.5:0.5b",
)
MODEL_REGISTRY: dict[str, dict[str, str]] = {
    name: {
        "color": "yellow",
        "quality_tier": "not_evaluated",
        "rationale": "Configured candidate only; no versioned local quality or hardware-fit result is available.",
    }
    for name in CONFIGURED_MODEL_NAMES
}

CANDIDATE_PULLS: list[dict[str, str]] = [
    {
        "name": "bge-m3",
        "purpose": "Candidate learned-dense embedding upgrade for retrieval experiments.",
        "fit": "Not acquired or benchmarked here; verify license, dimensions, latency, and memory before use.",
    },
    {
        "name": "qwen3:8b-q4_K_M",
        "purpose": "Local answer-model comparison candidate.",
        "fit": "No local service, digest, or fit measurement is available; acquire explicitly before testing.",
    },
    {
        "name": "mistral-nemo:12b",
        "purpose": "Local answer-model comparison candidate.",
        "fit": "Hardware fit and answer quality were not measured; benchmark before use.",
    },
    {
        "name": "gemma3:12b",
        "purpose": "Local answer-model comparison candidate.",
        "fit": "Hardware fit and answer quality were not measured; benchmark before use.",
    },
]


def model_metadata(model_name: str) -> dict[str, str]:
    if model_name in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_name]
    return {
        "color": "yellow",
        "quality_tier": "not_evaluated",
        "rationale": "Model availability may be reported by Ollama, but no versioned local quality or fit result is available.",
    }


def read_latest_benchmark(path: Path = BENCHMARK_RESULTS_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid", "path": str(path), "warnings": ["Latest Ollama benchmark JSON is invalid."]}


def benchmark_by_model(path: Path = BENCHMARK_RESULTS_PATH) -> dict[str, dict[str, Any]]:
    payload = read_latest_benchmark(path)
    if not payload or payload.get("status") == "invalid":
        return {}
    rows = payload.get("results", [])
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = str(row.get("model") or "")
        if not model:
            continue
        entry = summary.setdefault(
            model,
            {
                "runs": 0,
                "average_total_seconds": 0.0,
                "average_tokens_per_second": 0.0,
                "citation_compliance_rate": 0.0,
                "average_quality_score": 0.0,
            },
        )
        entry["runs"] += 1
        entry["average_total_seconds"] += float(row.get("total_seconds") or 0.0)
        entry["average_tokens_per_second"] += float(row.get("tokens_per_second") or 0.0)
        entry["citation_compliance_rate"] += 1.0 if row.get("citation_compliant") else 0.0
        entry["average_quality_score"] += float(row.get("quality_score") or 0.0)
    for entry in summary.values():
        runs = max(int(entry["runs"]), 1)
        entry["average_total_seconds"] = round(float(entry["average_total_seconds"]) / runs, 3)
        entry["average_tokens_per_second"] = round(float(entry["average_tokens_per_second"]) / runs, 2)
        entry["citation_compliance_rate"] = round(float(entry["citation_compliance_rate"]) / runs, 3)
        entry["average_quality_score"] = round(float(entry["average_quality_score"]) / runs, 3)
    return summary


def list_ollama_models(
    *,
    base_url: str | None = None,
    timeout: float = 2.0,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    settings = get_settings()
    resolved_base = (base_url or settings.ollama_base_url).rstrip("/")
    warnings: list[str] = []
    try:
        response = httpx.get(f"{resolved_base}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        warnings.append(f"Ollama is not reachable at {resolved_base}: {exc}")
        fallback = [{"name": name, "installed": False, "source": "configured_registry"} for name in MODEL_REGISTRY]
        return fallback, warnings, False

    models: list[dict[str, Any]] = []
    for raw in payload.get("models", []):
        name = str(raw.get("name") or raw.get("model") or "").strip()
        if not name:
            continue
        models.append(
            {
                "name": name,
                "installed": True,
                "source": "ollama",
                "size": raw.get("size"),
                "digest": raw.get("digest"),
                "modified_at": raw.get("modified_at"),
                "details": raw.get("details") or {},
            }
        )
    return models, warnings, True


def local_llm_status() -> dict[str, Any]:
    settings = get_settings()
    models, warnings, available = list_ollama_models(base_url=settings.ollama_base_url)
    benchmark_summary = benchmark_by_model()
    warnings.append(
        "Configured model names and pull candidates are unranked inventory suggestions; no quality or hardware-fit claim is made without a versioned benchmark."
    )
    enriched = []
    for model in models:
        metadata = model_metadata(model["name"])
        enriched.append(
            {
                **model,
                **metadata,
                "benchmark": benchmark_summary.get(model["name"]),
                "is_default": model["name"] == settings.ollama_default_model,
            }
        )
    return {
        "available": available,
        "base_url": settings.ollama_base_url,
        "default_model": settings.ollama_default_model,
        "model_count": sum(1 for model in enriched if model.get("installed")),
        "models": enriched,
        "candidate_pulls": CANDIDATE_PULLS,
        "recommended_pulls": CANDIDATE_PULLS,  # deprecated response key retained for client compatibility
        "benchmark": read_latest_benchmark(),
        "warnings": warnings,
    }
