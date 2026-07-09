from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

BENCHMARK_RESULTS_PATH = Path("data/evaluation/ollama_benchmark_results.json")

MODEL_REGISTRY: dict[str, dict[str, str]] = {
    "qwen3:4b-instruct-2507-q4_K_M": {
        "color": "green",
        "quality_tier": "recommended",
        "rationale": "Best default candidate from the installed small instruct models for paper Q&A.",
    },
    "gemma3:4b-it-q4_K_M": {
        "color": "green",
        "quality_tier": "recommended",
        "rationale": "Strong general-purpose 4B instruction model that should fit comfortably on the RTX 3080.",
    },
    "phi3.5:3.8b-mini-instruct-q4_K_M": {
        "color": "light_green",
        "quality_tier": "good",
        "rationale": "Compact instruction model likely to be fast and useful for concise grounded answers.",
    },
    "ministral-3:3b-instruct-2512-q4_K_M": {
        "color": "light_green",
        "quality_tier": "good",
        "rationale": "Small instruct model that should be quick enough for interactive demos.",
    },
    "llama3.2:3b": {
        "color": "light_green",
        "quality_tier": "good",
        "rationale": "Reliable small baseline model for local answer composition.",
    },
    "phi3:mini": {
        "color": "yellow",
        "quality_tier": "usable",
        "rationale": "Older compact model; useful as a baseline but not the first recommendation.",
    },
    "smollm2:1.7b": {
        "color": "yellow",
        "quality_tier": "usable",
        "rationale": "Very lightweight; useful for speed comparisons but likely weaker on academic synthesis.",
    },
    "smollm2:360m": {
        "color": "red",
        "quality_tier": "not_recommended",
        "rationale": "Tiny model; useful as a speed floor but not recommended for thesis-quality answers.",
    },
    "qwen2.5:0.5b": {
        "color": "red",
        "quality_tier": "not_recommended",
        "rationale": "Very small model; likely too weak for reliable grounded research Q&A.",
    },
}

RECOMMENDED_PULLS: list[dict[str, str]] = [
    {
        "name": "bge-m3",
        "purpose": "Recommended retrieval/embedding upgrade for smarter semantic search.",
        "fit": "Comfortable on 32 GB RAM and RTX 3080 when used for embeddings.",
    },
    {
        "name": "qwen3:8b-q4_K_M",
        "purpose": "Higher-quality local answer model candidate.",
        "fit": "Likely practical with controlled context and quantization.",
    },
    {
        "name": "mistral-nemo:12b",
        "purpose": "Quality candidate for deeper synthesis benchmarks.",
        "fit": "Test carefully with 4K-8K context because 10 GB VRAM may be tight.",
    },
    {
        "name": "gemma3:12b",
        "purpose": "Quality candidate for comparison against the installed 4B model.",
        "fit": "May be tight on 10 GB VRAM; benchmark before demo use.",
    },
]


def model_metadata(model_name: str) -> dict[str, str]:
    if model_name in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_name]
    lowered = model_name.lower()
    if any(marker in lowered for marker in ("0.5b", "360m")):
        return {
            "color": "red",
            "quality_tier": "not_recommended",
            "rationale": "Very small model; use only for speed comparisons.",
        }
    if any(marker in lowered for marker in ("1.7b", "mini")):
        return {
            "color": "yellow",
            "quality_tier": "usable",
            "rationale": "Compact model; useful for baseline testing but review answer quality carefully.",
        }
    if any(marker in lowered for marker in ("3b", "4b")):
        return {
            "color": "light_green",
            "quality_tier": "good",
            "rationale": "Small instruct-class model likely practical for local demos.",
        }
    return {
        "color": "yellow",
        "quality_tier": "unknown",
        "rationale": "Model was discovered locally but has not been categorized yet.",
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
        "recommended_pulls": RECOMMENDED_PULLS,
        "benchmark": read_latest_benchmark(),
        "warnings": warnings,
    }
