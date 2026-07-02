# TTLAB Research Intelligence Platform

Public-facing research discovery foundation for TTLAB publications. This project extends the publication archive system described in **“Automating the Collection, Display, Summarization and Podcasting of Academic Research”** by preparing the data layer needed for full-paper inspection, citation-grounded search, extension recommendations, summaries, podcasts, and evaluation.

This repository is currently in **Phase 1**. It discovers TTLAB publication metadata and PDF/source URLs, imports reviewed seed JSON into SQLite, exposes a minimal FastAPI API, and displays records in a small React dashboard. It does not yet implement RAG, LLM answers, summaries, podcast generation, or the Thesis Extension Finder.

## Repository Layout

```text
backend/   FastAPI app, SQLModel models, ingestion CLIs, pytest tests
frontend/  React + Vite + TypeScript dashboard and paper browser
data/      Seed JSON, PDFs, generated text/chunks/indexes, evaluation data
docs/      Scope, system design, evaluation plan, and demo script
```

## Backend Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

## Discover TTLAB Publications

The discovery command starts at the WordPress publications archive, follows controlled pagination, and writes both the raw discovered seed file and `data/seed/papers.json`.

```bash
PYTHONPATH=backend python -m app.ingestion.ttlab_page discover \
  --url https://lab.tt/index.php/category/pub/ \
  --max-pages 2 \
  --out data/seed/ttlab_publications_discovered.json
```

The scraper does not visit Google Scholar or scrape external publisher pages. Direct PDF URLs are detected from download text, `.pdf` URLs, or PDF content type checks. Publisher/DOI links are stored as `source_url`.

## Import Seed Data

```bash
PYTHONPATH=backend python -m app.ingestion.manual_import \
  --seed data/seed/ttlab_publications_discovered.json
```

This upserts papers into `data/papers.db`, creates simple author rows, preserves raw scraped values, and keeps all imported records at `review_status = "needs_review"`.

## PDF Downloader Foundation

The downloader is dry-run by default and only handles direct PDF candidates.

```bash
PYTHONPATH=backend python -m app.ingestion.pdf_downloader \
  --seed data/seed/ttlab_publications_discovered.json \
  --limit 5
```

Add `--download` to save verified PDFs under `data/pdfs/`.

## Run The Backend

```bash
PYTHONPATH=backend uvicorn app.main:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /api/papers`
- `GET /api/papers/{paper_id}`
- `GET /api/stats`

## Run The Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the backend at `http://localhost:8000`. Override with `VITE_API_BASE` if needed.

## Tests And Builds

```bash
python -m pytest
cd frontend
npm run build
```

The backend tests use HTML fixtures and temporary SQLite databases, so they do not depend on live network access.

## Current Limitations

- Metadata extraction is best-effort and review-first.
- PDF text extraction is not implemented yet; direct PDF records use `pdf_text_status = "not_extracted"`.
- No semantic search, vector index, RAG Q&A, LLM summaries, podcast scripts, admin editing, or extension recommendations are implemented in Phase 1.
- The live TTLAB archive markup may change; fixture tests protect the parser contract, while live discovery should be re-run before demos.
