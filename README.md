# TTLAB Research Intelligence Platform

Public-facing research discovery foundation for TTLAB publications. This project extends the publication archive system described in **“Automating the Collection, Display, Summarization and Podcasting of Academic Research”** by preparing the data layer needed for full-paper inspection, citation-grounded search, extension recommendations, summaries, podcasts, and evaluation.

This repository is currently through **Phase 8**. It discovers TTLAB publication metadata and PDF/source URLs, imports reviewed seed JSON into SQLite, downloads a controlled subset of direct PDFs, extracts full text page-by-page, creates deterministic source chunks, builds keyword and local hashing semantic indexes, exposes retrieval and citation-grounded Ask APIs, adds a Thesis Extension Finder, generates paper-level intelligence artifacts plus text-only podcast script drafts from cited chunks, provides local/demo admin review plus an evaluation dashboard, and now includes a deterministic Topic/Author Explorer with related-paper recommendations. It does not implement authentication, audio generation, production email, complex graph visualization, or deployment.

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

## Ask TTLAB

Ask TTLAB answers questions using retrieved source chunks. The default provider is offline and extractive: it selects relevant sentences from retrieved chunks and cites those chunks. It works without API keys and should be treated as a source-grounded draft, not a verified final research claim.

Build indexes first:

```bash
PYTHONPATH=backend python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend python -m app.indexing.embedder index --provider hashing
```

Ask from the CLI:

```bash
PYTHONPATH=backend python -m app.intelligence.rag_answerer ask \
  "Which TTLAB papers discuss RAG?" \
  --mode hybrid \
  --top-k 5
```

Run QA evaluation after creating manually reviewed labels:

```bash
PYTHONPATH=backend python -m app.evaluation.qa_eval \
  --questions data/evaluation/qa_questions.jsonl \
  --mode hybrid \
  --top-k 5
```

`data/evaluation/qa_questions.sample.jsonl` is only a template and intentionally has empty gold labels.

## Thesis Extension Finder

The Thesis Extension Finder is the Phase 5 differentiating feature. A student provides interests, skills, available time, project type, data constraints, and preferred difficulty. The backend retrieves relevant source chunks, groups them by paper, scores candidates deterministically, and returns ranked recommendations with citations.

Each recommendation separates:

- source-supported paper facts,
- explicit or inferred limitations/future-work evidence,
- the system's suggested extension idea,
- why it fits the student profile,
- an MVP scope and evaluation plan.

The default provider is `offline_deterministic` and works without external API keys. It uses templates and retrieved chunks; it does not invent paper facts. If no explicit future-work or limitation chunk is found, the gap is marked `not_found` or `inferred_from_paper`, and the run becomes partial rather than fully grounded.

Prepare local data for useful recommendations:

```bash
PYTHONPATH=backend python -m app.ingestion.pdf_downloader --from-db --limit 25 --download
PYTHONPATH=backend python -m app.ingestion.pdf_parser extract --limit 25
PYTHONPATH=backend python -m app.indexing.chunker chunk --limit 25
PYTHONPATH=backend python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend python -m app.indexing.embedder index --provider hashing
```

Run the recommendation CLI:

```bash
PYTHONPATH=backend python -m app.intelligence.extension_recommender recommend \
  --interests "RAG, web apps, education" \
  --skills Python React FastAPI \
  --available-time semester \
  --project-type "software prototype" \
  --data-constraints "prefer public or synthetic data" \
  --preferred-difficulty medium \
  --top-k 5 \
  --mode hybrid
```

Run extension recommendation evaluation:

```bash
PYTHONPATH=backend python -m app.evaluation.extension_eval \
  --cases data/evaluation/extension_eval_cases.jsonl \
  --top-k 5
```

The evaluation output records recommendation count, citation count, cited paper count, grounding status, citation coverage, and warning count. Human review scores are intentionally blank until a reviewer fills `data/evaluation/extension_human_review_template.csv`.

## Paper Intelligence Artifacts And Podcast Scripts

Phase 6 generates structured paper-level outputs for indexed papers:

- public summary
- technical summary
- contribution
- methods / approach
- limitations
- future work
- possible extensions
- required skills
- evaluation plan
- 3-5 minute text-only podcast script draft

Outputs are stored in SQLite as `PaperArtifact` rows and written to ignored local JSON under:

```text
data/generated/paper_artifacts/{paper_id}.json
```

The default provider is `offline_deterministic`. It works without external API keys by selecting section-aware chunks and filling deterministic templates. Optional external provider requests currently fall back to offline mode. Every generated artifact has `review_status = "needs_review"` and should be treated as AI-assisted, unreviewed draft material.

Generate artifacts for one paper:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator generate \
  --paper-id <paper_id> \
  --types paper_intelligence_bundle podcast_script \
  --provider auto \
  --max-chunks 12
```

Generate artifacts for the first five chunked papers:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator batch \
  --limit 5 \
  --types paper_intelligence_bundle podcast_script \
  --provider auto \
  --max-chunks 12
```

Show stored artifacts for a paper:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator show \
  --paper-id <paper_id>
```

Run artifact evaluation:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval \
  --cases data/evaluation/artifact_eval_cases.jsonl
```

Limitations and future work are marked `explicit`, `inferred`, or `not_found`. Possible extensions are marked `suggested_by_system` unless source chunks explicitly support them. Podcast scripts are text only; no audio/TTS is generated.

## Admin Review And Evaluation Dashboard

Phase 7 adds local/demo review tools. There is no login or role-based access control in this MVP; the UI clearly labels the admin area as unauthenticated local tooling.

Reviewable records use these statuses:

- `needs_review`
- `reviewed`
- `approved`
- `rejected`
- `needs_reprocess`

The Admin Review page can:

- correct paper metadata such as title, authors, year, venue, topics, source URL, PDF URL, abstract, and notes,
- approve/reject or mark paper artifacts, Ask TTLAB answers, and Thesis Extension Finder runs as needing review,
- record citation correctness and 1-5 faithfulness/usefulness scores for Ask answers,
- store corrected artifact text or corrected recommendation JSON when practical,
- write a `ReviewEvent` audit row for every review/correction action.

The Evaluation page is read-only. It reads existing result JSON under `data/evaluation/` and reports `not_run` when files are missing rather than inventing metrics.

Run evaluation commands:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.extension_eval --cases data/evaluation/extension_eval_cases.jsonl --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval --cases data/evaluation/artifact_eval_cases.jsonl
```

Optional combined runner:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.run_all
```

Human review templates are available under `data/evaluation/` for extension recommendations and paper artifacts. Human scores remain blank until reviewed.

## Topic/Author Explorer

Phase 8 adds a public-facing explorer for TTLAB topics, authors, and related papers. It is deterministic and does not call an LLM.

Topic sources include reviewed paper topics when available, paper metadata, title/venue text, chunk sections and text, and generated paper artifacts such as technical summaries, contributions, possible extensions, and required skills. A small synonym map merges obvious variants such as `rag` / `retrieval augmented generation`, `ai` / `artificial intelligence`, `ml` / `machine learning`, `iot` / `internet of things`, and `optimisation` / `optimization`.

Reviewed paper topics are not overwritten. If a paper has reviewed or approved topics, the explorer uses those as the source of truth for that paper's topic links. Author expertise summaries are derived from indexed authorship and topic links only; they are not supervisor-availability claims.

Rebuild explorer links:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
```

Inspect a topic:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
```

Optional bounded demo prep:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

The demo prep helper imports seed data if needed, downloads/extracts/chunks only up to the requested limit, rebuilds keyword and hashing indexes, rebuilds the explorer, and optionally generates artifacts for the first five chunked papers. Generated PDFs, extracted text, chunks, indexes, artifacts, and SQLite files remain local/ignored.

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
- `POST /api/ask`
- `GET /api/ask/{answer_id}`
- `GET /api/ask/history`
- `GET /api/ask/diagnostics`
- `POST /api/recommendations/extensions`
- `GET /api/recommendations/extensions/{recommendation_id}`
- `GET /api/recommendations/extensions/history`
- `GET /api/recommendations/extensions/diagnostics`
- `POST /api/papers/{paper_id}/artifacts/generate`
- `GET /api/papers/{paper_id}/artifacts`
- `GET /api/papers/{paper_id}/artifacts/{artifact_type}`
- `POST /api/papers/artifacts/generate-batch`
- `GET /api/artifacts/diagnostics`
- `GET /api/admin/overview`
- `GET /api/admin/review-queue`
- `PATCH /api/admin/papers/{paper_id}`
- `PATCH /api/admin/artifacts/{artifact_id}/review`
- `PATCH /api/admin/recommendations/{recommendation_id}/review`
- `PATCH /api/admin/answers/{answer_id}/review`
- `PATCH /api/admin/extraction/{paper_id}/review`
- `GET /api/admin/review-events`
- `GET /api/evaluation/dashboard`
- `GET /api/explorer/overview`
- `GET /api/topics`
- `GET /api/topics/{topic_id}`
- `GET /api/authors`
- `GET /api/authors/{author_id}`
- `GET /api/papers/{paper_id}/related`
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
PYTHONPATH=backend .venv/bin/python -m pytest
cd frontend
npm run build
```

The backend tests use HTML fixtures and temporary SQLite databases, so they do not depend on live network access.

## Current Limitations

- Metadata extraction is best-effort and review-first.
- Only a controlled subset of direct PDFs should be downloaded/extracted/chunked during early demos.
- PDF extraction uses embedded text only; scanned/image-only PDFs are flagged instead of OCR'd.
- Semantic search uses local deterministic hashing embeddings by default, not a model download or API.
- Ask TTLAB uses an offline extractive provider by default; optional external provider support is non-required and does not affect offline mode.
- Ask TTLAB answers must cite source chunks or be marked unsupported.
- Thesis Extension Finder suggestions are generated project ideas, not verified paper claims; paper facts and gap evidence must be checked against citations.
- External recommendation providers are optional and not required for the MVP; the offline deterministic provider is the supported default.
- Paper intelligence artifacts and podcast scripts are AI-assisted and unreviewed; citations and support status must be checked before public use.
- Admin review is local/demo tooling only and has no authentication or role-based access control.
- Evaluation dashboard metrics are file-backed and only as valid as the reviewed test cases used to generate them.
- Topic and author relationships are deterministic/inferred unless reviewed.
- Author expertise summaries are derived only from indexed TTLAB papers and topics; they do not confirm supervisor availability.
- Related-paper scoring is simple and explainable, using shared authors/topics, venue/year proximity, metadata keywords, and local semantic similarity when the hashing index exists.
- Podcast output is script text only; no audio generation or TTS pipeline is implemented.
- No authentication, complex graph visualization, production email, or deployment features are implemented yet.
- The live TTLAB archive markup may change; fixture tests protect the parser contract, while live discovery should be re-run before demos.
