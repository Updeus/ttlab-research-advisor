from __future__ import annotations

from fastapi import APIRouter

from app.intelligence.local_llms import local_llm_status, read_latest_benchmark

router = APIRouter(prefix="/api/llms", tags=["llms"])


@router.get("/local")
def local_llms() -> dict[str, object]:
    return local_llm_status()


@router.get("/benchmark/latest")
def latest_llm_benchmark() -> dict[str, object]:
    payload = read_latest_benchmark()
    if payload is None:
        return {
            "status": "not_run",
            "path": "data/evaluation/ollama_benchmark_results.json",
            "results": [],
            "summary": {},
            "warnings": ["No local Ollama benchmark has been run yet."],
        }
    return payload
