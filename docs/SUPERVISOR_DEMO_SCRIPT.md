# Supervisor Demo Script

## Demo Goal

Show in 7-10 minutes that the TTLAB Research Intelligence Platform transforms a publication archive into a source-grounded research advisor for students, researchers, and public/industry users.

## Suggested Demo Questions

- "Which papers discuss RAG or retrieval augmented generation?"
- "What research relates to agriculture or AI?"
- "Which paper could I extend if I know Python, React, and FastAPI?"
- "Who appears to work on optimization or machine learning?"

## Setup

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
uvicorn app.main:app --reload --app-dir backend
cd frontend && npm run dev
```

Open `http://127.0.0.1:5173`.

## 7-10 Minute Flow

1. Dashboard
   - Show indexed/imported papers, PDFs, extracted papers, chunks, topics, authors, paper artifacts, review queue count, and evaluation file status.
   - Talking point: this is a bounded local MVP, but it already covers the complete research intelligence flow.

2. Papers
   - Browse TTLAB papers.
   - Point out title, authors, year/date, venue, source link, PDF status, and review status.
   - Talking point: metadata is preserved and review-first; unknown fields are not invented.

3. Paper Detail
   - Open a paper with extracted chunks.
   - Show metadata, PDF/text extraction status, page/word diagnostics, chunk previews with page ranges, and related papers.
   - Talking point: the platform inspects full papers, not only abstracts.

4. Paper Intelligence
   - In the same paper detail page, show:
     - public summary,
     - technical summary,
     - contribution,
     - methods,
     - limitations,
     - future work,
     - possible extensions,
     - required skills,
     - evaluation plan,
     - podcast script.
   - Point out citations/page ranges and support statuses: `explicit`, `inferred`, `not_found`, and `suggested_by_system`.
   - Talking point: generated content is AI-assisted and unreviewed until approved.

5. Search
   - Search for `RAG academic research`, then switch keyword,
     feature-hashing (legacy `semantic`), and hybrid modes if useful.
   - Show retrieved full-paper chunks, snippets, source papers, and page ranges.
   - Talking point: search returns source evidence before any generated answer.

6. Ask TTLAB
   - Ask: "Which papers discuss RAG or retrieval augmented generation?"
   - Show the answer, grounding status, citations, paper titles, snippets, and page ranges.
   - Talking point: unsupported or weakly grounded answers are labeled rather than hidden.

7. Thesis Extension Finder
   - Use:
     - interests: `RAG, web apps, education`
     - skills: `Python, React, FastAPI`
     - available time: `semester`
     - project type: `software prototype`
     - data constraints: `prefer public or synthetic data`
     - difficulty: `medium`
   - Show ranked recommendations, why the paper fits, source-supported facts, identified gap support status, suggested extension, MVP scope, stretch goals, required skills, skills gap, data availability, risk, implementation time, evaluation plan, citations, and potential researcher fit.
   - Talking point: this is the killer feature for students choosing feasible thesis/project extensions.

8. Topic/Author Explorer
   - Open Topic/Author Explorer.
   - Show top topics and top authors.
   - Open a topic such as RAG, optimization, AI, or agriculture.
   - Open an author detail page and show papers, topics, coauthors, venues, and the source-derived expertise notice.
   - Talking point: author expertise is derived from indexed papers and topics; it is not a supervisor availability claim.

9. Admin Review
   - Open Admin Review.
   - Show the no-auth local-demo notice.
   - Approve/reject or return one artifact to `needs_review`, or add reviewer notes to an Ask answer or recommendation.
   - If safe, correct one metadata field.
   - Show the Review Events audit trail.
   - Talking point: the platform is responsible about generated outputs and review status.

10. Evaluation Dashboard
   - Open Evaluation.
   - Show retrieval, QA, extension, and artifact evaluation sections.
   - Point out `not_run` where result files are missing and human review template availability.
   - Talking point: metrics are only as valid as the manually reviewed gold/test cases.

11. Close
   - Summarize what is implemented: discovery, full-paper extraction, chunks, retrieval, grounded Q&A, thesis recommendations, paper intelligence, podcast scripts, topics/authors, admin review, and evaluation.
   - State limitations clearly:
     - no authentication,
     - no production deployment,
     - no audio/TTS,
     - no production email,
     - no OCR for scanned PDFs,
     - generated outputs need review before public use.

## Backup CLI Evidence

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
PYTHONPATH=backend .venv/bin/python -m app.intelligence.rag_answerer ask "Which papers discuss RAG or retrieval augmented generation?" --mode hybrid --top-k 5
```
