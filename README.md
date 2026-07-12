# TTLAB Research Intelligence Platform

**Tagline:** From publication archive to source-grounded research advisor.

This project is a local/demo research intelligence platform for TTLAB publications. It extends **"Automating the Collection, Display, Summarization and Podcasting of Academic Research"** by moving beyond metadata and abstracts into full-paper inspection, citation-grounded search/Q&A, thesis extension recommendations, paper intelligence outputs, topic/author exploration, admin review, and evaluation evidence.

The system is designed for a two-week MVP: polished enough to demonstrate, bounded enough to understand, and careful about separating source-supported paper facts from AI-assisted suggestions.

## What It Solves

- Helps students find TTLAB papers they can extend into projects or theses.
- Helps researchers and the public understand TTLAB work through cited summaries, search, and paper relationships.
- Gives reviewers a local workflow to inspect metadata and generated outputs before public use.
- Provides evaluation scaffolding so retrieval, Q&A, recommendation, and artifact quality are not overclaimed.

## Architecture

```text
backend/   FastAPI, SQLModel, SQLite, ingestion, indexing, intelligence, evaluation, tests
frontend/  React + Vite + TypeScript public/demo interface
data/      Seed files plus ignored local PDFs, extracted text, chunks, indexes, generated artifacts, DB
docs/      Scope, design, evaluation, demo, final status, reproducibility evidence
```

Backend storage is SQLite. Search uses keyword FTS/fallback matching plus local deterministic hashing embeddings. The default intelligence providers are offline/deterministic; optional external provider boundaries exist but are not required.

## Feature Summary

- TTLAB publication discovery from `https://lab.tt/index.php/category/pub/`
- Seed import into SQLite
- Safe direct-PDF downloader
- PyMuPDF full-paper extraction
- Page-aware chunking
- Keyword, 256-dimensional feature-hashing, and hybrid retrieval. The current
  API value `semantic` is a legacy name for the hashing baseline; it is not a
  learned semantic encoder.
- Ask TTLAB citation-grounded Q&A
- Local Ollama model support for Ask TTLAB with red/yellow/green model recommendations
- Thesis Extension Finder with cited recommendations
- Paper Intelligence artifacts: public summary, technical summary, contribution, methods, limitations, future work, extensions, required skills, evaluation plan
- Text-only podcast script generation
- Topic/Author Explorer and related papers
- Local/demo Admin Review with audit trail
- Evaluation Dashboard for retrieval, QA, extension, and artifact result files
- Offline/mock provider support and optional external provider boundary

See [docs/LOCAL_LLM_RAG_README.md](docs/LOCAL_LLM_RAG_README.md) for the local Ollama model selector, benchmark workflow, smarter RAG changes, and hardware notes.

## Quickstart

One-command local demo:

```bash
./scripts/run_everything.sh
```

The one-command script checks `http://127.0.0.1:11434/api/tags` and starts `ollama serve` when Ollama is installed but not already running. It then starts/reuses the backend and frontend.

Useful variants:

```bash
./scripts/run_everything.sh --skip-downloads
./scripts/run_everything.sh --serve-only
./scripts/run_everything.sh --serve-only --no-ollama
./scripts/run_everything.sh --verify-only
```

Manual setup:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

Prepare a bounded local demo dataset:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

This bounded helper is for UI demonstration only. At the audited baseline it
could replace a complete shared vector file with a partial 25-record hashing
index, so it must not be used to create research results or to assert full index
coverage. The remediation work tracks that defect as `DATA-03` in
[`docs/REVIEW_REMEDIATION_MATRIX.md`](docs/REVIEW_REMEDIATION_MATRIX.md).

Run backend:

```bash
uvicorn app.main:app --reload --app-dir backend
```

Run frontend:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

## Local Ollama Q&A

Ask TTLAB can use local Ollama models as answer composers while keeping retrieval, citations, page ranges, and grounding checks mandatory.

Check installed models:

```bash
ollama list
```

Run a local benchmark across installed models:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.ollama_benchmark --models installed
```

List model status through the backend:

```bash
curl http://127.0.0.1:8000/api/llms/local
```

The default local model is `qwen3:4b-instruct-2507-q4_K_M`. If Ollama is unavailable, Ask TTLAB falls back to the offline extractive provider and shows a warning.

When using the one-command demo launcher, Ollama is started automatically unless you pass `--no-ollama`.

## Manual Data Commands

Discover TTLAB publications:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.ttlab_page discover \
  --url https://lab.tt/index.php/category/pub/ \
  --max-pages 2 \
  --out data/seed/ttlab_publications_discovered.json
```

Import seed data:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.manual_import \
  --seed data/seed/ttlab_publications_discovered.json
```

Prepare local PDFs, text, chunks, indexes, topics, and sample artifacts:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_downloader --from-db --limit 25 --download
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_parser extract --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.chunker chunk --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider hashing
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator batch \
  --limit 5 \
  --types paper_intelligence_bundle podcast_script \
  --provider auto \
  --max-chunks 12
```

## Useful CLI Commands

Ask TTLAB:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.rag_answerer ask \
  "Which TTLAB papers discuss RAG?" \
  --mode hybrid \
  --top-k 5
```

Run the Thesis Extension Finder:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.extension_recommender recommend \
  --interests "RAG, web apps, education" \
  --skills Python React FastAPI \
  --available-time semester \
  --project-type "software prototype" \
  --data-constraints "prefer public or synthetic data" \
  --preferred-difficulty medium \
  --top-k 5 \
  --mode hybrid
```

Inspect a topic:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
```

Run local smoke check:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
```

## Backend API Highlights

- `GET /health`
- `GET /api/stats`
- `GET /api/papers`
- `GET /api/search?q=RAG&mode=hybrid`
- `POST /api/ask`
- `POST /api/recommendations/extensions`
- `POST /api/papers/{paper_id}/artifacts/generate`
- `GET /api/explorer/overview`
- `GET /api/topics`
- `GET /api/authors`
- `GET /api/papers/{paper_id}/related`
- `GET /api/admin/overview`
- `GET /api/evaluation/dashboard`

## Evaluation Commands

Evaluation files are under `data/evaluation/`. Sample files are placeholders until manually reviewed gold labels or human scores are added.

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.extension_eval --cases data/evaluation/extension_eval_cases.jsonl --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval --cases data/evaluation/artifact_eval_cases.jsonl
PYTHONPATH=backend .venv/bin/python -m app.evaluation.run_all
```

Automatic metrics only measure against provided gold/test files. They do not replace supervisor/manual review.

## Tests And Build

```bash
PYTHONPATH=backend .venv/bin/python -m pytest

cd frontend
npm run build
```

## Screenshots

Current interface screenshots are committed under `thesis/figures/screenshots/`.
Use [docs/screenshots/README.md](docs/screenshots/README.md) for their capture
and refresh checklist; screenshots are dated evidence and must be regenerated
after material UI or data-state changes.

## Local Data And Git Hygiene

Local runtime artifacts are ignored:

- SQLite databases
- downloaded PDFs
- extracted text
- chunks
- indexes
- generated paper artifacts
- evaluation result JSON

Seed files and evaluation templates are tracked. Runtime PDFs, extracted text,
chunks, indexes, generated records, and SQLite databases stay ignored. The two
compiled document deliverables, `build/thesis.pdf` and
`build/ieee-paper.pdf`, are explicit tracked exceptions.

## Limitations

- Generated outputs are source-grounded where possible, but they are AI-assisted drafts and need review before public use.
- No authentication or role-based access control is implemented.
- No production deployment is included.
- No production email notifications.
- No audio/TTS generation.
- No OCR for scanned PDFs.
- No complex graph visualization.
- Topic labels and author expertise are deterministic/inferred unless reviewed.
- Author expertise is derived from indexed TTLAB papers only and does not confirm supervisor availability.
- External LLM providers are optional; offline deterministic providers are the supported default.

## Future Work

- Supervisor-reviewed gold evaluation sets and human scores.
- Admin-reviewed public release workflow.
- OCR for scanned PDFs.
- Better topic normalization and author identity resolution.
- Optional production deployment plan.
- Optional external LLM provider validation.
- Optional audio generation after scripts have been reviewed.
