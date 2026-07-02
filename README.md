# TTLAB Research Intelligence Platform

Public-facing research discovery foundation for TTLAB publications. This project extends the publication archive system described in **“Automating the Collection, Display, Summarization and Podcasting of Academic Research”** by preparing the data layer needed for full-paper inspection, citation-grounded search, extension recommendations, summaries, podcasts, and evaluation.

This repository is currently through **Phase 3**. It discovers TTLAB publication metadata and PDF/source URLs, imports reviewed seed JSON into SQLite, downloads a controlled subset of direct PDFs, extracts full text page-by-page, creates deterministic source chunks, builds keyword and local hashing semantic indexes, exposes retrieval APIs, and displays records in a small React dashboard/browser/detail/search UI. It does not yet implement chatbot/RAG answer generation, LLM calls, summaries, podcast generation, or the Thesis Extension Finder.

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

## Download Direct PDFs

The downloader is dry-run by default, only handles direct PDF URLs, verifies content type/signature, and does not follow DOI or publisher pages.

```bash
PYTHONPATH=backend python -m app.ingestion.pdf_downloader \
  --from-db \
  --limit 10 \
  --download
```

Use `--paper-id <paper_id>` for a specific record. Use `--include-existing` to consider already-downloaded PDFs, and `--overwrite` to replace files.

## Extract Full Paper Text

PDF text extraction uses PyMuPDF and writes both structured page JSON and plain text:

```bash
PYTHONPATH=backend python -m app.ingestion.pdf_parser extract --limit 10
```

Outputs:

- `data/extracted_text/{paper_id}.json`
- `data/extracted_text/{paper_id}.txt`

The database stores page count, word/character counts, pages with/without text, possible scanned-PDF warnings, and extraction status.

## Chunk Extracted Text

Chunking is deterministic, page-aware, and does not use an LLM:

```bash
PYTHONPATH=backend python -m app.indexing.chunker chunk --limit 10
```

Outputs:

- `data/chunks/{paper_id}.json`
- SQLite `chunk` rows with `chunk_id`, `page_start`, `page_end`, `section`, text, counts, and source hash.

## Build Search Indexes

Rebuild the keyword index:

```bash
PYTHONPATH=backend python -m app.indexing.keyword_search rebuild
```

Build the local/offline semantic index with deterministic hashing embeddings:

```bash
PYTHONPATH=backend python -m app.indexing.embedder index --provider hashing --limit 10
```

Test hybrid retrieval:

```bash
PYTHONPATH=backend python -m app.indexing.retriever search "RAG academic research" --mode hybrid --top-k 5
```

Run retrieval evaluation after creating a manually reviewed `data/evaluation/questions.jsonl`:

```bash
PYTHONPATH=backend python -m app.evaluation.retrieval_eval \
  --questions data/evaluation/questions.jsonl \
  --mode hybrid \
  --top-k 5
```

`data/evaluation/questions.sample.jsonl` is only a template and intentionally has empty gold labels.

## Run The Backend

```bash
uvicorn app.main:app --reload --app-dir backend
```

Useful endpoints:

- `GET /health`
- `GET /api/papers`
- `GET /api/papers/{paper_id}`
- `GET /api/papers/{paper_id}/extraction`
- `GET /api/papers/{paper_id}/chunks`
- `GET /api/chunks/search?q=...`
- `GET /api/search?q=...&mode=hybrid&limit=10`
- `GET /api/search/diagnostics`
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
- Only a controlled subset of direct PDFs should be downloaded/extracted/chunked during early demos.
- PDF extraction uses embedded text only; scanned/image-only PDFs are flagged instead of OCR'd.
- Semantic search uses local deterministic hashing embeddings by default, not a model download or API.
- Retrieval returns source chunks only; it does not generate answers.
- No RAG Q&A, LLM summaries, podcast scripts, admin editing, or extension recommendations are implemented yet.
- The live TTLAB archive markup may change; fixture tests protect the parser contract, while live discovery should be re-run before demos.
