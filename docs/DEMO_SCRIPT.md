# Demo Script

## Goal

Show, in 7-10 minutes, that the TTLAB Research Intelligence Platform is more than a publication list. It discovers TTLAB papers, inspects full-paper text, retrieves cited evidence, recommends thesis extensions, explains paper intelligence outputs, exposes topics/authors, and supports responsible review/evaluation.

## Optional Demo Prep

Use bounded local prep. Do not process every paper by default.

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

Manual prep commands, if running step-by-step:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_downloader --from-db --limit 25 --download
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_parser extract --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.chunker chunk --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider hashing
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator batch --limit 5 --types paper_intelligence_bundle podcast_script --provider auto --max-chunks 12
```

Start the app:

```bash
uvicorn app.main:app --reload --app-dir backend
cd frontend && npm run dev
```

## 7-10 Minute Flow

1. Dashboard
   - Show imported papers, PDFs, extracted PDFs, chunks, keyword and
     feature-hashing indexes, artefacts, admin review queue, evaluation files,
     topics, authors, and papers with topics. The baseline API may still expose
     the hashing mode under the legacy name `semantic`.
   - Talking point: the system is local, bounded, and traceable.

2. Papers
   - Browse TTLAB records.
   - Open a paper with extracted chunks.
   - Show metadata, source/PDF links, extraction status, page/word diagnostics, and chunk previews.

3. Paper Intelligence
   - In the paper detail page, show public summary, technical summary, contribution, methods, limitations, future work, possible extensions, required skills, evaluation plan, and text-only podcast script.
   - Point out citations/page ranges, support statuses such as `explicit`, `inferred`, `not_found`, and `suggested_by_system`, and `needs_review`.

4. Search
   - Run a hybrid search such as `RAG academic research` or `mobile network optimization`.
   - Show source chunks, page ranges, and paper links.
   - Talking point: search returns evidence, not unsupported prose.

5. Ask TTLAB
   - Ask a question such as "Which TTLAB papers discuss RAG?"
   - Show the generated-answer notice, grounding status, citations, retrieved chunks, and page references.

6. Thesis Extension Finder
   - Enter interests, skills, timeline, project type, data constraints, and difficulty.
   - Show ranked papers, source-supported facts, identified gap support status, suggested extension, MVP scope, stretch goals, skills gap, data availability, risk, implementation time, evaluation plan, citations, and potential researcher fit.
   - Talking point: this is the platform's differentiating feature for students.

7. Topic/Author Explorer
   - Open Topic/Author Explorer.
   - Show overview cards, top topics, top authors, topic detail, author detail, related topics, source-basis evidence, and paper links.
   - Open an author and show papers, top topics, coauthors, venues, and the source-derived expertise notice.
   - Return to a paper detail page and show related papers with reasons such as shared topic, shared author, shared venue, shared keywords, or semantic similarity.

8. Admin Review
   - Show the local-demo no-auth notice.
   - Open the review queue.
   - Approve/reject one artifact or update notes on an Ask answer or Thesis recommendation.
   - Edit a paper metadata field if needed.
   - Show the Review Events audit trail.

9. Evaluation Dashboard
   - Show retrieval, QA, extension, and artifact evaluation sections.
   - Explain `not_run` for missing result files and that metrics are only valid when gold/test cases are reviewed.
   - Point out human review templates.

10. Close With Limitations
   - No authentication, deployment, production email, audio/TTS, or complex graph visualization.
   - Topics and author expertise are deterministic/inferred unless reviewed.
   - Scanned PDFs are flagged but not OCR'd.
   - Generated outputs are AI-assisted drafts and remain review-first.

## Useful CLI Checks

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
PYTHONPATH=backend .venv/bin/python -m app.intelligence.extension_recommender recommend --interests "RAG, web apps, education" --skills Python React FastAPI --available-time semester --project-type "software prototype" --data-constraints "prefer public or synthetic data" --preferred-difficulty medium --top-k 5 --mode hybrid
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.extension_eval --cases data/evaluation/extension_eval_cases.jsonl --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval --cases data/evaluation/artifact_eval_cases.jsonl
```

## Verification

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
cd frontend && npm run build
```
