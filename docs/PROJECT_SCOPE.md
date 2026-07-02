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

## Phase 6 Goal

Add paper-level intelligence artifacts and text-only podcast script generation. This phase creates public summaries, technical summaries, contribution/methods/limitations/future-work sections, possible extensions, required skills, evaluation plans, and 3-5 minute podcast script drafts from full-paper chunks. Artifacts are persisted in SQLite, written to ignored local JSON, cited back to source chunks, and shown on the paper detail page.

## Phase 7 Goal

Add local/demo admin review and an evaluation dashboard. This phase lets a reviewer correct paper metadata, update review status for papers, Ask answers, Thesis Extension Finder runs, extraction status, and paper artifacts, capture reviewer notes and quality scores where appropriate, and preserve every action as a `ReviewEvent`. It also adds a read-only dashboard that summarizes retrieval, QA, extension, and artifact evaluation result files without inventing missing metrics.

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
- Paper intelligence artifact APIs, CLI, persisted records, diagnostics, and stats metrics.
- Paper detail Paper Intelligence section with generated-content notice, support status, review status, citations, and text-only podcast script display.
- Local/demo Admin Review page with overview cards, review queue, paper metadata correction, artifact review, Ask answer review, thesis recommendation review, and audit events.
- Admin Review API for local review/correction actions. No authentication or role-based access control is included in this phase.
- Review status normalization for papers, Ask answers, thesis recommendations, and paper artifacts.
- `ReviewEvent` audit trail for review/correction actions.
- Read-only Evaluation Dashboard API/page that parses existing result JSON and reports `not_run` for missing files.
- Retrieval evaluation code for manually reviewed gold paper IDs.
- QA evaluation code for manually reviewed gold paper IDs.
- Extension recommendation evaluation scaffold for citation coverage and human review templates.
- Artifact evaluation scaffold for citation coverage and human review templates.
- Fixture-based parser/import/API/PDF/chunking/retrieval/Ask/extension/artifact tests.

## Explicitly Out Of Scope For Phase 1/2/3/4/5/6/7

- Authentication.
- Role-based access control.
- Production deployment infrastructure.
- OCR for scanned PDFs.
- Complex topic/author graph visualization.
- Production email notifications.
- Audio generation or TTS.
- Full role-based review workflows.

## Review Principle

Discovered metadata is treated as unreviewed. Unknown or ambiguous fields remain blank/null, and imported records keep `review_status = "needs_review"`.

Generated chunks are source artifacts, not AI claims. They preserve page ranges so later RAG features can cite them.

Retrieval results are also source artifacts. They show ranked chunks with page references, not synthesized answers.

Ask TTLAB answers are generated drafts, but every answer must cite retrieved chunks or be marked partial/unsupported.

Thesis Extension Finder outputs are generated project suggestions. Paper facts must cite retrieved chunks. Future-work/limitation evidence is labeled `explicit_in_paper`, `inferred_from_paper`, or `not_found`. Suggestions must not be presented as verified facts, and potential researcher fit is based only on source-paper authorship.

Paper intelligence artifacts are AI-assisted and unreviewed by default. They start at `review_status = "needs_review"` and can be approved/rejected in the local Phase 7 admin workflow. Limitations and future work are labeled `explicit`, `inferred`, or `not_found`; possible extensions are labeled `suggested_by_system`; podcast scripts are text-only drafts with citations.

Admin review changes the review status and notes for local demo data, but it is not a production publishing workflow. Every action writes a `ReviewEvent` with item type, item ID, action, previous/new status, reviewer name, notes, and optional diffs. Review statuses mean:

- `needs_review`: generated or imported content has not been checked.
- `reviewed`: a reviewer has checked the item without formally approving it.
- `approved`: a reviewer considers it acceptable for demo use.
- `rejected`: the item should not be used as-is.
- `needs_reprocess`: extraction or generation should be rerun or manually inspected.

The Evaluation Dashboard is evidence-only. If a result file does not exist, it reports `not_run`; it does not create or imply performance metrics.
