# Local Ollama LLMs and Smarter RAG

This document explains the local LLM upgrade for the TTLAB Research Intelligence Platform.

The goal is not to replace citation-grounded retrieval. The goal is to let local Ollama models write clearer answers after the system has already retrieved source chunks from TTLAB papers.

Generated answers remain AI-assisted and unreviewed until checked. Citations, page ranges, source chunks, grounding status, and warnings remain mandatory.

## Why Add Local LLMs

The original platform used deterministic extractive answers. That is safe and offline, but it can sound stitched together and may miss the intent of a student's question.

Ollama support improves the project by allowing:

- more natural Ask TTLAB answers;
- single-paper Q&A from the paper detail page;
- local/offline demonstration without paid API keys;
- model comparison on the user's own hardware;
- repeatable speed and quality baselines for later optimization.

The local LLM is only the answer composer. The indexed TTLAB chunks remain the source of truth.

## Current Installed Model Tiers

The UI displays local models from red to green. These colors are preliminary until benchmarks are run.

| Tier | Models | Meaning |
| --- | --- | --- |
| Green | `qwen3:4b-instruct-2507-q4_K_M`, `gemma3:4b-it-q4_K_M` | Recommended first for local Ask TTLAB |
| Light green | `phi3.5:3.8b-mini-instruct-q4_K_M`, `ministral-3:3b-instruct-2512-q4_K_M`, `llama3.2:3b` | Good practical baselines |
| Yellow | `phi3:mini`, `smollm2:1.7b` | Usable, but review quality carefully |
| Red | `smollm2:360m`, `qwen2.5:0.5b` | Not recommended except for speed comparisons |

The default local model is:

```bash
qwen3:4b-instruct-2507-q4_K_M
```

## Hardware Assumptions

Target demo hardware:

- 32 GB system RAM
- NVIDIA RTX 3080 with 10 GB VRAM
- Ollama running locally at `http://localhost:11434`

The installed 3B-4B quantized models should fit comfortably. Larger models can work if context size is controlled, but they should be benchmarked before being used in a demo.

Recommended future pulls:

```bash
ollama pull bge-m3
ollama pull qwen3:8b-q4_K_M
ollama pull mistral-nemo:12b
ollama pull gemma3:12b
```

`bge-m3` is recommended first as a retrieval/embedding upgrade. Better retrieval usually improves RAG more than simply using a larger answer model.

## Speed Optimizations

The Ollama provider uses conservative defaults:

- bounded context: `num_ctx=4096`;
- short answer generation: bounded `num_predict`;
- low temperature: `0.1`;
- model warm retention: `keep_alive=10m`;
- compact citation pack: only the strongest retrieved chunks are passed to the model.

These choices keep the UI responsive while preserving source grounding.

## Smarter RAG Changes

The retrieval layer now adds deterministic improvements before answer generation:

- query expansion for terms such as `RAG`, `AI`, `ML`, and optimization/optimisation;
- metadata-aware scoring using paper title, authors, venue, and topics;
- section boosts for method, evaluation, limitations, future work, abstract, introduction, and conclusion matches;
- diversity ranking to reduce repeated adjacent chunks;
- paper-specific Ask mode through `paper_id`.

The model still cannot mark an answer grounded by itself. Grounding status is assigned after citation verification.

## API Usage

List local LLMs:

```bash
curl http://127.0.0.1:8000/api/llms/local
```

Start the full local demo, including Ollama when it is installed but not already running:

```bash
./scripts/run_everything.sh
```

Serve-only mode also checks Ollama:

```bash
./scripts/run_everything.sh --serve-only
```

Skip Ollama only when you intentionally want offline fallback behavior:

```bash
./scripts/run_everything.sh --serve-only --no-ollama
```

Get latest benchmark:

```bash
curl http://127.0.0.1:8000/api/llms/benchmark/latest
```

Ask with a local model:

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which TTLAB papers discuss RAG?",
    "mode": "hybrid",
    "top_k": 5,
    "audience": "student",
    "max_words": 250,
    "provider": "ollama",
    "model": "qwen3:4b-instruct-2507-q4_K_M"
  }'
```

Ask about one paper:

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the strongest cited points in this paper?",
    "mode": "hybrid",
    "top_k": 5,
    "audience": "student",
    "max_words": 250,
    "provider": "ollama",
    "model": "qwen3:4b-instruct-2507-q4_K_M",
    "paper_id": "<paper_id>"
  }'
```

## Benchmarking

Run the local model benchmark:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.ollama_benchmark --models installed
```

Outputs:

```text
data/evaluation/ollama_benchmark_results.json
data/evaluation/ollama_benchmark_results.csv
```

These files are generated local evidence and are ignored by git.

The benchmark records:

- cold/first response time;
- warm response time;
- tokens per second when reported by Ollama;
- citation compliance;
- refusal behavior when context does not support the answer;
- simple heuristic answer quality score.

This is an initial optimization baseline, not a final academic quality claim. Human review is still needed for thesis evaluation.

## Limitations

- Ollama must be running locally for model answers.
- If Ollama fails, the system falls back to the offline extractive provider.
- Model colors are preliminary until benchmark results exist.
- Small models may produce fluent but weak answers; citations and grounding warnings must be checked.
- Benchmarks are machine-specific and depend on model quantization, context size, GPU state, and whether the model is already loaded.
- The app does not use local models for authentication, deployment, audio generation, or unsupported claims.
