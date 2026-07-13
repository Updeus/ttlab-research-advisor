from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.intelligence.llm_provider import OllamaProvider
from app.intelligence.local_llms import BENCHMARK_RESULTS_PATH, list_ollama_models, model_metadata

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "case_id": "rag-global",
        "question": "Which papers discuss RAG or retrieval augmented generation?",
        "expected_terms": ["retrieval", "generation", "citations"],
        "expected_refusal": False,
        "context_chunks": [
            {
                "chunk_id": "bench-rag-001",
                "title": "RAG Paper",
                "section": "Introduction",
                "page_start": 1,
                "page_end": 2,
                "snippet": "Retrieval augmented generation combines search with retrieved paper chunks to ground answers with citations.",
            }
        ],
    },
    {
        "case_id": "specific-paper-method",
        "question": "What method does this paper use?",
        "expected_terms": ["method", "evaluation", "prototype"],
        "expected_refusal": False,
        "context_chunks": [
            {
                "chunk_id": "bench-method-001",
                "title": "Research Advisor Prototype",
                "section": "Methodology",
                "page_start": 3,
                "page_end": 4,
                "snippet": "The method builds a software prototype, indexes paper chunks, and evaluates retrieval quality with citation checks.",
            }
        ],
    },
    {
        "case_id": "no-evidence-refusal",
        "question": "What does this paper say about volcanic mineral policy?",
        "expected_terms": [],
        "expected_refusal": True,
        "context_chunks": [
            {
                "chunk_id": "bench-unrelated-001",
                "title": "Traffic Paper",
                "section": "Results",
                "page_start": 5,
                "page_end": 6,
                "snippet": "The paper reports highway congestion measurements and traffic behavior results.",
            }
        ],
    },
]


def load_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return DEFAULT_CASES
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases or DEFAULT_CASES


def resolve_models(model_args: list[str]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    if not model_args or model_args == ["installed"]:
        models, model_warnings, available = list_ollama_models()
        warnings.extend(model_warnings)
        if not available:
            return [], warnings
        return [str(model["name"]) for model in models if model.get("installed")], warnings
    return model_args, warnings


def run_case(model: str, case: dict[str, Any], *, phase: str) -> dict[str, Any]:
    provider = OllamaProvider(model_name=model)
    start = time.perf_counter()
    draft = provider.generate_answer(
        str(case["question"]),
        list(case.get("context_chunks", [])),
        audience="general",
        max_words=180,
    )
    wall_seconds = round(time.perf_counter() - start, 3)
    metrics = draft.prompt_metadata.get("ollama_metrics", {})
    citation_compliant = answer_has_citation(draft.answer_text, list(case.get("context_chunks", [])))
    refusal_correct = evaluate_refusal(draft.answer_text, bool(case.get("expected_refusal")))
    quality_score = score_answer(
        draft.answer_text,
        expected_terms=list(case.get("expected_terms", [])),
        citation_compliant=citation_compliant,
        refusal_correct=refusal_correct,
        expected_refusal=bool(case.get("expected_refusal")),
    )
    total_seconds = metrics.get("total_seconds") if isinstance(metrics, dict) else None
    tokens_per_second = metrics.get("tokens_per_second") if isinstance(metrics, dict) else None
    return {
        "model": model,
        "phase": phase,
        "case_id": case["case_id"],
        "provider": draft.provider,
        "response_model": draft.model,
        "total_seconds": total_seconds if total_seconds is not None else wall_seconds,
        "wall_seconds": wall_seconds,
        "tokens_per_second": tokens_per_second,
        "citation_compliant": citation_compliant,
        "refusal_correct": refusal_correct,
        "quality_score": quality_score,
        "answer_preview": draft.answer_text[:360],
        "warnings": draft.warnings,
        "ollama_metrics": metrics,
    }


def run_benchmark(
    *,
    models: list[str],
    cases: list[dict[str, Any]],
    output_path: Path = BENCHMARK_RESULTS_PATH,
    progress: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not models:
        warnings.append("No installed Ollama models were available to benchmark.")
    for model in models:
        for case in cases:
            if progress:
                print(f"benchmarking model={model} case={case['case_id']} phase=cold_or_first", flush=True)
            results.append(run_case(model, case, phase="cold_or_first"))
            if progress:
                print(f"benchmarking model={model} case={case['case_id']} phase=warm", flush=True)
            results.append(run_case(model, case, phase="warm"))
    payload = {
        "status": "available" if results else "not_run",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at,
        "machine_scope": "local_machine_baseline",
        "hardware_note": "Benchmarks are specific to the current machine, model quantization, context size, and Ollama runtime state.",
        "default_model": get_settings().ollama_default_model,
        "case_count": len(cases),
        "model_count": len(models),
        "results": results,
        "summary": summarize_results(results),
        "warnings": warnings,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(payload, output_path.with_suffix(".csv"))
    return payload


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for result in results:
        model = result["model"]
        entry = summary.setdefault(
            model,
            {
                "model": model,
                **model_metadata(model),
                "runs": 0,
                "average_total_seconds": 0.0,
                "average_tokens_per_second": 0.0,
                "citation_compliance_rate": 0.0,
                "refusal_correct_rate": 0.0,
                "average_quality_score": 0.0,
            },
        )
        entry["runs"] += 1
        entry["average_total_seconds"] += float(result.get("total_seconds") or 0.0)
        entry["average_tokens_per_second"] += float(result.get("tokens_per_second") or 0.0)
        entry["citation_compliance_rate"] += 1.0 if result.get("citation_compliant") else 0.0
        entry["refusal_correct_rate"] += 1.0 if result.get("refusal_correct") else 0.0
        entry["average_quality_score"] += float(result.get("quality_score") or 0.0)
    for entry in summary.values():
        runs = max(int(entry["runs"]), 1)
        entry["average_total_seconds"] = round(float(entry["average_total_seconds"]) / runs, 3)
        entry["average_tokens_per_second"] = round(float(entry["average_tokens_per_second"]) / runs, 2)
        entry["citation_compliance_rate"] = round(float(entry["citation_compliance_rate"]) / runs, 3)
        entry["refusal_correct_rate"] = round(float(entry["refusal_correct_rate"]) / runs, 3)
        entry["average_quality_score"] = round(float(entry["average_quality_score"]) / runs, 3)
    return summary


def write_csv(payload: dict[str, Any], path: Path) -> None:
    fieldnames = [
        "model",
        "phase",
        "case_id",
        "provider",
        "response_model",
        "total_seconds",
        "wall_seconds",
        "tokens_per_second",
        "citation_compliant",
        "refusal_correct",
        "quality_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in payload.get("results", []):
            writer.writerow({field: result.get(field) for field in fieldnames})


def answer_has_citation(answer: str, chunks: list[dict[str, Any]]) -> bool:
    lowered = answer.lower()
    return any(str(chunk.get("chunk_id") or "").lower() in lowered for chunk in chunks)


def evaluate_refusal(answer: str, expected_refusal: bool) -> bool:
    if not expected_refusal:
        return True
    lowered = answer.lower()
    return any(phrase in lowered for phrase in ["not enough evidence", "do not contain", "not supported", "indexed chunks"])


def score_answer(
    answer: str,
    *,
    expected_terms: list[str],
    citation_compliant: bool,
    refusal_correct: bool,
    expected_refusal: bool,
) -> float:
    if expected_refusal:
        return 1.0 if refusal_correct else 0.0
    lowered = answer.lower()
    term_score = 0.0
    if expected_terms:
        term_score = sum(1 for term in expected_terms if term.lower() in lowered) / len(expected_terms)
    citation_score = 0.35 if citation_compliant else 0.0
    length_score = 0.15 if 20 <= len(answer.split()) <= 220 else 0.05
    return round(min(1.0, term_score * 0.5 + citation_score + length_score), 3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark local Ollama models for source-cited Ask TTLAB answers.")
    parser.add_argument("--models", nargs="+", default=["installed"], help="Use 'installed' or pass one or more Ollama model names.")
    parser.add_argument("--questions", type=Path, default=None, help="Optional JSONL cases file.")
    parser.add_argument("--out", type=Path, default=BENCHMARK_RESULTS_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    models, warnings = resolve_models(args.models)
    cases = load_cases(args.questions)
    for warning in warnings:
        print(f"warning={warning}")
    payload = run_benchmark(models=models, cases=cases, output_path=args.out, progress=True)
    print(f"status={payload['status']} model_count={payload['model_count']} case_count={payload['case_count']}")
    print(f"json={args.out}")
    print(f"csv={args.out.with_suffix('.csv')}")
    for model, summary in payload.get("summary", {}).items():
        print(
            f"{model}: color={summary['color']} avg_seconds={summary['average_total_seconds']} "
            f"tokens_per_second={summary['average_tokens_per_second']} quality={summary['average_quality_score']}"
        )
    for warning in payload.get("warnings", []):
        print(f"warning={warning}")


if __name__ == "__main__":
    main()
