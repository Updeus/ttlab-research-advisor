# Project Scope

## Phase 1 Goal

Set up a two-week-MVP foundation for the TTLAB Research Intelligence Platform. This phase discovers publication metadata from the TTLAB WordPress publications archive, stores it in seed JSON, imports it into SQLite, exposes minimal read APIs, and displays a dashboard/browser.

## Phase 2 Goal

Make the platform inspect full PDFs safely. This phase downloads a limited subset of direct PDF URLs, extracts full text page-by-page, records extraction diagnostics, creates deterministic page-aware chunks, stores chunk metadata in SQLite, and exposes extraction/chunk status in the API and frontend.

## Phase 3 Goal

Make extracted chunks searchable. This phase adds keyword search, local/offline semantic search, hybrid retrieval, retrieval APIs, a frontend Search page, and basic retrieval evaluation scaffolding.

## Phase 4 Goal

Add Ask TTLAB citation-grounded Q&A over indexed chunks. This phase retrieves source chunks, drafts concise answers with the offline extractive provider, verifies citations, stores answers, exposes Ask APIs/CLI, and adds a frontend Ask page.

## Phase 5 Goal

Add the Thesis Extension Finder. This phase lets a student enter interests, skills, timeline, project type, data constraints, preferred difficulty, and optional topic preferences. It retrieves indexed TTLAB chunks, ranks papers with deterministic scoring, generates structured thesis extension suggestions, cites source chunks, persists recommendation runs, exposes API/CLI/UI access, and adds evaluation scaffolding.

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
- Ask TTLAB page with grounding status, citations, snippets, and retrieved chunks.
- Thesis Extension Finder page with ranked, citation-grounded paper recommendations and structured project scopes.
- Extension recommendation APIs, CLI, persisted history, diagnostics, and stats metrics.
- Retrieval evaluation code for manually reviewed gold paper IDs.
- QA evaluation code for manually reviewed gold paper IDs.
- Extension recommendation evaluation scaffold for citation coverage and human review templates.
- Fixture-based parser/import/API/PDF/chunking/retrieval/Ask/extension tests.

## Explicitly Out Of Scope For Phase 1/2/3/4/5

- LLM summaries.
- Podcast script generation.
- Admin correction UI.
- Authentication.
- Production deployment infrastructure.
- OCR for scanned PDFs.
- Complex topic/author graph visualization.
- Production email notifications.

## Review Principle

Discovered metadata is treated as unreviewed. Unknown or ambiguous fields remain blank/null, and imported records keep `review_status = "needs_review"`.

Generated chunks are source artifacts, not AI claims. They preserve page ranges so later RAG features can cite them.

Retrieval results are also source artifacts. They show ranked chunks with page references, not synthesized answers.

Ask TTLAB answers are generated drafts, but every answer must cite retrieved chunks or be marked partial/unsupported.

Thesis Extension Finder outputs are generated project suggestions. Paper facts must cite retrieved chunks. Future-work/limitation evidence is labeled `explicit_in_paper`, `inferred_from_paper`, or `not_found`. Suggestions must not be presented as verified facts, and potential researcher fit is based only on source-paper authorship.
