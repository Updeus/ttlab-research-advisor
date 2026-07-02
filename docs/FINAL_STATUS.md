# Final Status

## Project Title

TTLAB Research Intelligence Platform

## Tagline

From publication archive to source-grounded research advisor.

## Problem Solved

TTLAB has a public publication archive, but students, researchers, and public/industry users need more than a list of papers. They need to search full-paper content, understand papers at different levels of detail, ask grounded questions, discover topics/authors, and identify feasible thesis or project extensions.

This platform turns a publication archive into a local, demo-ready research intelligence system.

## Extension Of The Original Paper

The original paper, **"Automating the Collection, Display, Summarization and Podcasting of Academic Research"**, focused on publication collection, display, lay summarization, email notifications, and manual podcast preparation.

This project extends that work by adding:

- full-paper PDF inspection instead of abstract-only metadata;
- page-aware chunks with citations;
- keyword, semantic, and hybrid retrieval;
- citation-grounded Ask TTLAB Q&A;
- Thesis Extension Finder for student project ideas;
- paper intelligence bundles with public and technical outputs;
- text-only podcast script generation with traceability;
- Topic/Author Explorer and related-paper discovery;
- local admin review and audit events;
- evaluation dashboard and reproducibility documentation.

## Implemented Features

- TTLAB publication discovery and seed JSON generation.
- Seed import into SQLite.
- Safe direct-PDF download.
- Full-paper extraction with PyMuPDF.
- Page-aware chunking.
- Keyword search.
- Offline semantic search with hashing embeddings.
- Hybrid retrieval.
- Ask TTLAB citation-grounded Q&A.
- Thesis Extension Finder with cited recommendations and support-status labeling.
- Paper Intelligence artifacts:
  - public summary,
  - technical summary,
  - contribution,
  - methods,
  - limitations,
  - future work,
  - possible extensions,
  - required skills,
  - evaluation plan.
- Text-only podcast script drafts.
- Admin Review page and local audit trail.
- Evaluation Dashboard.
- Topic Explorer.
- Author Explorer.
- Related papers.
- Bounded demo preparation helper.
- Local smoke-check helper.

## Intentionally Not Implemented

- Authentication.
- Role-based access control.
- Production deployment infrastructure.
- Production email notifications.
- Audio/TTS generation.
- OCR for scanned PDFs.
- Complex graph visualization.
- New LLM/generation features beyond the existing offline deterministic providers and optional provider boundaries.

## Current Local Demo Dataset

The local demo data is generated and ignored by Git. At the last verified rebuild:

- 134 papers were available in SQLite.
- 83 papers had extracted text locally.
- 651 full-paper chunks were available locally.
- 688 paper-topic links were built.
- 1024 author-topic links were built.
- 39 topics and 126 authors were available through the explorer.
- 14 paper artifact records were available locally.

Local PDFs, extracted text, chunk JSON, indexes, generated paper artifacts, evaluation result JSON, and SQLite databases are intentionally ignored.

## Grounding And Review

Generated outputs are source-grounded where possible through citations, source chunk IDs, page ranges, and snippets. Generated outputs are still AI-assisted drafts and need review before public use.

Review status is explicit. Admin Review can approve, reject, mark items as needing review/reprocess, add notes, and create `ReviewEvent` audit rows.

External LLM providers are optional. The default behavior works offline with deterministic providers.

## Known Limitations

- Topic labels are deterministic/inferred unless reviewed.
- Author expertise is derived only from indexed papers and does not verify supervisor availability.
- Some papers may lack direct PDF URLs.
- Scanned/image-heavy PDFs are flagged but not OCR'd.
- Evaluation quality depends on manually reviewed gold/test files.
- The platform is local/demo only and does not include authentication or production deployment.

## Future Work

- Add manually reviewed evaluation gold sets and human quality scores.
- Improve author identity normalization.
- Add OCR for scanned PDFs.
- Add reviewed public publishing workflow.
- Add optional production deployment plan.
- Add optional external LLM provider validation.
- Add audio generation only after podcast scripts have been reviewed.

## Latest Verification Commands

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
cd frontend && npm run build
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
```

Latest final hardening verification:

- Backend tests: `56 passed`.
- Frontend build: passed.
- Demo prep: completed with warnings and produced 134 papers, 83 extracted papers, 651 chunks, 39 topics, 126 authors, and 14 artifacts.
- Smoke check: `PASS`.

One PDF download attempt failed during the final demo prep because its host could not be resolved. The command reported the failure and continued using the existing local demo dataset.
