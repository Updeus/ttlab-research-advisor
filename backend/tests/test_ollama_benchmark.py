from pathlib import Path

from app.evaluation import ollama_benchmark
from app.intelligence.llm_provider import LLMAnswerDraft


def test_ollama_benchmark_writes_json_and_csv(monkeypatch, tmp_path: Path) -> None:
    def fake_generate(self, question, context_chunks, audience="general", max_words=250):
        chunk_id = context_chunks[0]["chunk_id"]
        return LLMAnswerDraft(
            answer_text=f"Mock answer for {question} cites [{chunk_id}] and uses retrieval evidence.",
            provider="ollama",
            model=self.model,
            prompt_metadata={
                "ollama_metrics": {
                    "total_seconds": 1.2,
                    "tokens_per_second": 35.0,
                    "eval_count": 42,
                }
            },
        )

    monkeypatch.setattr("app.intelligence.llm_provider.OllamaProvider.generate_answer", fake_generate)
    output_path = tmp_path / "ollama_benchmark_results.json"

    payload = ollama_benchmark.run_benchmark(
        models=["qwen3:4b-instruct-2507-q4_K_M"],
        cases=[ollama_benchmark.DEFAULT_CASES[0]],
        output_path=output_path,
    )

    assert payload["status"] == "available"
    assert output_path.exists()
    assert output_path.with_suffix(".csv").exists()
    summary = payload["summary"]["qwen3:4b-instruct-2507-q4_K_M"]
    assert summary["color"] == "yellow"
    assert summary["quality_tier"] == "not_evaluated"
    assert "no versioned local quality or hardware-fit result" in summary["rationale"]
    assert summary["average_tokens_per_second"] == 35.0


def test_ollama_benchmark_reports_no_models(tmp_path: Path) -> None:
    output_path = tmp_path / "empty_results.json"

    payload = ollama_benchmark.run_benchmark(models=[], cases=ollama_benchmark.DEFAULT_CASES[:1], output_path=output_path)

    assert payload["status"] == "not_run"
    assert "No installed Ollama models" in payload["warnings"][0]
