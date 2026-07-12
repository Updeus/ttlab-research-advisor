# Project Status

## Current Milestone

Phase 8 is implemented: Topic/Author Explorer plus demo polish.

The platform currently supports:

- TTLAB publication discovery and seed import.
- Controlled direct-PDF download.
- Full-paper text extraction and page-aware chunks.
- Keyword, local feature-hashing (legacy `semantic`), and hybrid retrieval.
- Citation-grounded Ask TTLAB.
- Thesis Extension Finder with cited source facts and clearly labeled suggestions.
- Paper intelligence artifacts and text-only podcast scripts.
- Local/demo Admin Review and audit events.
- Evaluation Dashboard that reads result files without inventing metrics.
- Topic/Author Explorer with deterministic topic links, author profiles, and related-paper reasons.

## Local Demo Data

The local demo can be prepared with:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

The helper is intentionally bounded for UI demonstration. In the audited
baseline it could overwrite the shared hashing file with a partial index, so it
must not be used for research evaluation or as proof of complete coverage.

Runtime PDFs, extracted text, chunk JSON, index files, generated artifacts, and
SQLite databases are local artefacts and should not be committed. The compiled
thesis and IEEE paper under `build/` are explicit tracked deliverables.

## Review And Grounding

Generated outputs are AI-assisted and unreviewed by default. The UI and API preserve this through:

- citations and chunk IDs,
- grounding status,
- review status,
- reviewer notes,
- support status for limitations/future work,
- `suggested_by_system` labels for generated extension ideas,
- `ReviewEvent` audit records for local review actions.

Topic and author relationships are deterministic and source-derived. Reviewed topics are respected during rebuilds; inferred links preserve evidence showing why the topic was assigned.

## Known Limitations

- No authentication or role-based access control.
- No production deployment or production email notifications.
- No audio/TTS generation.
- No OCR for scanned PDFs.
- No complex graph visualization.
- Topic labels and author expertise are deterministic/inferred unless reviewed.
- Author profiles are derived only from indexed TTLAB papers and do not confirm supervisor availability.
- Evaluation dashboard metrics are only meaningful when result files were generated from manually reviewed cases.

## Core Commands

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
cd frontend && npm run build
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
uvicorn app.main:app --reload --app-dir backend
cd frontend && npm run dev
```
