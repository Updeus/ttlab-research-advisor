# Project Scope

## Phase 1 Goal

Set up a two-week-MVP foundation for the TTLAB Research Intelligence Platform. This phase discovers publication metadata from the TTLAB WordPress publications archive, stores it in seed JSON, imports it into SQLite, exposes minimal read APIs, and displays a dashboard/browser.

## Phase 2 Goal

Make the platform inspect full PDFs safely. This phase downloads a limited subset of direct PDF URLs, extracts full text page-by-page, records extraction diagnostics, creates deterministic page-aware chunks, stores chunk metadata in SQLite, and exposes extraction/chunk status in the API and frontend.

## Phase 3 Goal

Make extracted chunks searchable. This phase adds keyword search, local/offline semantic search, hybrid retrieval, retrieval APIs, a frontend Search page, and basic retrieval evaluation scaffolding.

## In Scope Now

- FastAPI backend scaffold.
- SQLite database setup through SQLModel.
- Paper, Author, and placeholder Chunk models.
- Deterministic TTLAB publication discovery from `https://lab.tt/index.php/category/pub/`.
- Controlled pagination with `--max-pages`.
- Direct PDF/source URL classification.
- Dry-run-safe direct PDF downloader.
- Seed JSON import into SQLite.
- Minimal React dashboard and paper browser.
- Paper detail view with extraction diagnostics and chunk previews.
- Search page with keyword, semantic, and hybrid modes.
- Retrieval evaluation code for manually reviewed gold paper IDs.
- Fixture-based parser/import/API/PDF/chunking/retrieval tests.

## Explicitly Out Of Scope For Phase 1/2/3

- RAG answer generation.
- Chatbot UI.
- LLM calls.
- LLM summaries.
- Thesis Extension Finder.
- Podcast script generation.
- Admin correction UI.
- Authentication.
- Production deployment infrastructure.
- OCR for scanned PDFs.

## Review Principle

Discovered metadata is treated as unreviewed. Unknown or ambiguous fields remain blank/null, and imported records keep `review_status = "needs_review"`.

Generated chunks are source artifacts, not AI claims. They preserve page ranges so later RAG features can cite them.

Retrieval results are also source artifacts. They show ranked chunks with page references, not synthesized answers.
