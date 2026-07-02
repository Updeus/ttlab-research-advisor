# AGENTS.md

# TTLAB Research Intelligence Platform — Agent Instructions

## Project Identity

This repository implements the **TTLAB Research Intelligence Platform**, a public-facing research discovery and research-advisor system.

It extends the paper:

**“Automating the Collection, Display, Summarization and Podcasting of Academic Research”**  
by Tristan Narine and Patrick Hosein.

The original paper automated publication collection, display, lay summarization, email notification, and manual podcast preparation. This project extends that idea into a deeper platform that inspects **full papers**, not just abstracts, and exposes TTLAB research to students, researchers, industry partners, and the general public.

Working title:

> From Publication Archive to Research Advisor: A RAG-Based Platform for Academic Discovery

---

## Main Product Goal

Build a polished but limited-scope platform that can be completed in approximately two weeks.

The platform should:

1. Ingest a small set of TTLAB papers and PDFs.
2. Extract full paper text.
3. Store clean paper metadata.
4. Chunk and index full papers.
5. Provide semantic search.
6. Provide citation-grounded RAG Q&A.
7. Generate public-friendly and technical summaries.
8. Recommend thesis/project extension ideas.
9. Show topic/author relationships.
10. Generate podcast scripts/transcripts.
11. Provide an evaluation dashboard for retrieval and grounding quality.
12. Support admin review/correction of metadata and generated outputs.

This is not only a chatbot. Treat it as a research intelligence system.

---

## Supervisor Direction

The supervisor approved the project direction and specifically requested:

- deeper inspection of full papers rather than only abstracts,
- exposure of TTLAB research to the general public,
- starting with a few papers first,
- scaling to all TTLAB papers after debugging,
- and potentially adding the system to the TTLAB website once functional.

Prioritize features that support those goals.

---

## Two-Week Scope Constraint

Do not overbuild.

The MVP must be demoable within two weeks. Prefer a small polished system over a large unfinished one.

Start with a few papers supplied by the supervisor. Later, the platform can ingest all TTLAB publications.

The first version should support:

- local development,
- manually supplied papers/PDFs,
- a small curated dataset,
- deterministic ingestion,
- citation-grounded search/Q&A,
- extension recommendation,
- clear UI,
- evaluation metrics.

Avoid production-scale infrastructure unless explicitly requested.

---

## Core User Stories

### Student

As a student, I want to find TTLAB papers that match my interests and receive project/thesis extension ideas.

The system should answer:

- Which papers can I extend?
- Which project is easiest to finish in one semester?
- Which paper matches my interests in RAG, web apps, AI, data science, agriculture, climate, networks, or optimization?
- What skills would I need?
- What would the MVP look like?
- How can I evaluate the extension?

### Researcher

As a researcher, I want my work to be understandable and discoverable.

The system should provide:

- technical summary,
- public summary,
- keywords/topics,
- related papers,
- possible applications,
- collaboration opportunities.

### Public / Industry User

As a public or industry user, I want to understand what TTLAB works on and find researchers or papers relevant to a problem.

The system should answer:

- Who works on RAG?
- What research relates to agriculture?
- Which papers have industrial applications?
- Which researcher might be suitable for collaboration?

### Administrator / Reviewer

As an administrator, I want to review and correct extracted metadata and generated summaries before public exposure.

The system should support:

- metadata review,
- generated summary review,
- topic correction,
- author correction,
- PDF extraction status,
- bad/chunked text diagnostics.

---

## Baseline Paper Features To Surpass

The original paper focused on:

- collecting publications,
- displaying researcher publication lists,
- ranking by recency/citations,
- lay summaries,
- email notifications,
- manual NotebookLM podcast generation,
- future RAG query support.

This project should improve on it by adding:

1. Full-paper ingestion instead of abstract-only processing.
2. Grounded RAG Q&A with source citations.
3. Research extension recommendation.
4. Topic/author exploration.
5. Admin review/correction.
6. Podcast script generation with traceability.
7. Evaluation dashboard.
8. Safer ingestion using local PDFs and cached metadata.
9. Clear separation between extracted facts and AI suggestions.

---

## Recommended Architecture

Use this architecture unless the existing repo strongly suggests otherwise:

```text
backend/
  app/
    main.py
    config.py
    db.py

    models/
      paper.py
      author.py
      chunk.py
      rag.py
      review.py
      evaluation.py

    ingestion/
      ttlab_page.py
      manual_import.py
      pdf_downloader.py
      pdf_parser.py
      metadata_cleaner.py

    indexing/
      chunker.py
      embedder.py
      vector_store.py
      keyword_search.py

    intelligence/
      rag_answerer.py
      citation_verifier.py
      summarizer.py
      extension_recommender.py
      podcast_script_generator.py
      topic_classifier.py

    evaluation/
      retrieval_eval.py
      qa_eval.py
      summary_eval.py

    api/
      papers.py
      search.py
      ask.py
      recommendations.py
      topics.py
      podcasts.py
      evaluation.py
      admin.py

  tests/

frontend/
  src/
    pages/
    components/
    api/
    types/
    styles/

data/
  seed/
  papers/
  pdfs/
  extracted_text/
  chunks/
  indexes/
  generated/
  evaluation/

docs/
  PROJECT_SCOPE.md
  SYSTEM_DESIGN.md
  EVALUATION_PLAN.md
  DEMO_SCRIPT.md
```

---

## Preferred Stack

Backend:

- Python
- FastAPI
- SQLite
- SQLAlchemy or SQLModel
- Pydantic
- PyMuPDF for PDF text extraction
- Optional fallback PDF parser if needed
- Local file storage for PDFs and extracted text

Frontend:

- React + Vite or Next.js
- TypeScript
- simple professional styling
- no heavy UI framework unless already present or justified

Search / RAG:

- Start simple and robust.
- Use a modular embedding provider.
- Support local embeddings or API-based embeddings.
- Store vector data in local files or SQLite-compatible form where practical.
- Do not make the system fail completely if embeddings/LLM provider keys are unavailable.

LLM:

- Implement provider abstraction.
- Do not hard-code one provider throughout the system.
- Generated content must include source references or source chunk IDs.
- The app must distinguish generated summaries from reviewed summaries.

---

## Important Design Principle

Every AI-generated answer must be traceable.

For Q&A, store and return:

```text
question
answer
retrieved chunks
paper IDs
page/section references if available
confidence or grounding status
unsupported-claim warnings if detected
model/provider metadata
timestamp
```

For summaries, store:

```text
paper_id
summary_type
generated_text
source_sections_used
model/provider metadata
review_status
reviewer_notes
timestamp
```

For extension recommendations, store:

```text
paper_id
baseline_work
identified_gap
extension_idea
mvp_scope
stretch_goals
required_skills
estimated_difficulty
risk_level
evaluation_plan
source_evidence
recommendation_rationale
```

Do not silently present AI suggestions as verified facts.

---

## Data Models

### Paper

A paper record should include:

```text
paper_id
title
authors
year
publication_date
venue
abstract
source_url
pdf_url
local_pdf_path
doi
keywords
topics
ingestion_status
pdf_text_status
review_status
created_at
updated_at
```

### Author

```text
author_id
name
affiliation
email optional
profile_url optional
research_topics
paper_count
review_status
```

### Chunk

```text
chunk_id
paper_id
page_start
page_end
section
text
token_count
embedding_status
source_hash
created_at
```

### RAG Answer

```text
answer_id
question
answer
retrieved_chunk_ids
cited_paper_ids
model
grounding_status
unsupported_claims
created_at
```

### Extension Idea

```text
extension_id
paper_id
title
problem
extension_summary
mvp
stretch_goals
skills_required
data_required
evaluation_plan
difficulty
risk_level
source_chunk_ids
created_at
review_status
```

---

## Required MVP Screens

### 1. Dashboard

Show:

- number of papers indexed,
- number of PDFs parsed,
- number of authors,
- top topics,
- ingestion errors,
- recent papers,
- evaluation status.

### 2. Paper Browser

Features:

- search,
- filters by year, author, topic, venue,
- paper cards,
- paper detail page,
- PDF/text extraction status,
- summaries,
- extension ideas,
- source link.

### 3. Ask TTLAB

Citation-grounded Q&A over indexed papers.

Must show:

- answer,
- cited papers,
- retrieved chunks/snippets,
- confidence/grounding status,
- “this is a generated answer” notice.

### 4. Thesis Extension Finder

Inputs:

```text
interests
skills
available time
project type
data constraints
preferred difficulty
```

Outputs:

```text
ranked papers
reason for recommendation
extension idea
MVP
stretch goals
evaluation plan
risk level
skills needed
```

This is the most important feature.

### 5. Topic / Author Explorer

Minimum version:

- topic list,
- paper count per topic,
- author list,
- author-paper links,
- related papers.

Advanced graph visualization is optional.

### 6. Podcast Script Generator

Generate:

- episode title,
- 3–5 minute script,
- two-speaker dialogue optional,
- transcript,
- cited source papers.

Audio generation is optional and should not block the MVP.

### 7. Evaluation Dashboard

Show:

- retrieval test questions,
- gold relevant papers,
- Recall@k,
- MRR,
- citation correctness checks,
- answer faithfulness review status,
- summary review status.

### 8. Admin Review

Allow review/correction of:

- metadata,
- authors,
- topics,
- summaries,
- extension ideas,
- bad PDF extraction.

---

## What Not To Build In The MVP

Do not build these unless explicitly requested:

- full login/auth system,
- complex role-based permissions,
- production email subscriptions,
- complete podcast audio pipeline,
- Google Scholar scraping as the main source,
- large distributed crawler,
- payment or API billing,
- mobile app,
- complicated deployment infrastructure,
- browser extension,
- automatic claims without source grounding,
- unrestricted scraping.

---

## Ingestion Rules

Start with manually supplied papers and PDFs.

The ingestion system must support:

1. `data/seed/papers.json`
2. local PDFs under `data/pdfs/`
3. optional source URLs
4. later TTLAB page scraping

Preferred initial seed format:

```json
[
  {
    "title": "Automating the Collection, Display, Summarization and Podcasting of Academic Research",
    "authors": ["Tristan Narine", "Patrick Hosein"],
    "year": 2025,
    "venue": "",
    "source_url": "",
    "pdf_path": "data/pdfs/narine-rtsi.pdf",
    "topics": ["research visibility", "summarization", "podcasting", "RAG"]
  }
]
```

The system should fail clearly on missing PDFs or extraction errors.

Do not invent metadata. Use empty fields or review-required status instead.

---

## Citation And Grounding Rules

RAG answers must cite source chunks.

Do not generate answers without retrieved context unless the UI explicitly labels the answer as unsupported or general.

The answer API should return:

```json
{
  "question": "...",
  "answer": "...",
  "citations": [
    {
      "paper_id": "...",
      "title": "...",
      "chunk_id": "...",
      "page_start": 2,
      "page_end": 3,
      "snippet": "..."
    }
  ],
  "grounding_status": "grounded|partial|unsupported"
}
```

If the answer contains claims not supported by retrieved chunks, mark them.

---

## Extension Recommendation Rules

The Thesis Extension Finder must separate:

- what the paper actually did,
- what the paper says as future work,
- what the system recommends as an extension,
- why the extension is feasible,
- how to evaluate it.

Each recommendation should include:

```text
difficulty: easy | medium | hard
risk: low | medium | high
data availability: public | needs supervisor | private | synthetic
implementation time: 2 weeks | 1 month | semester
MVP scope
stretch scope
evaluation method
```

The recommender must not pretend suggestions are stated in the paper unless they are source-supported.

---

## Podcast Rules

Podcast script generation is allowed.

MVP podcast output:

```text
episode title
short description
speaker roles
script
source papers
citations
transcript
```

Full audio generation is optional.

Do not block the MVP on TTS/audio quality.

---

## Evaluation Requirements

Add a small evaluation dataset under:

```text
data/evaluation/
```

It should include:

```text
questions.jsonl
```

Example format:

```json
{
  "question": "Which TTLAB papers discuss RAG?",
  "gold_paper_ids": ["..."],
  "answer_points": ["..."]
}
```

Minimum metrics:

- Recall@3
- Recall@5
- MRR
- number of cited sources
- citation correctness review status
- answer usefulness review status

If possible, add a small human review CSV:

```text
question
answer_id
faithfulness_score
usefulness_score
citation_correct
notes
```

Do not overclaim performance without evaluation evidence.

---

## Testing Rules

Before declaring a task complete, run relevant tests.

Backend:

```bash
python -m pytest
```

Frontend:

```bash
npm run build
```

Also add targeted tests for:

- seed ingestion,
- PDF extraction,
- chunking,
- search retrieval,
- RAG citation return,
- extension recommendation schema,
- evaluation metrics.

If a command cannot be run, say exactly why.

---

## Documentation Rules

Update documentation when adding major features.

Required docs:

```text
README.md
docs/PROJECT_SCOPE.md
docs/SYSTEM_DESIGN.md
docs/EVALUATION_PLAN.md
docs/DEMO_SCRIPT.md
```

The README should include:

- project purpose,
- how it extends the original paper,
- how to run backend/frontend,
- how to ingest seed papers,
- how to ask questions,
- how to generate extension recommendations,
- how to run evaluation.

---

## Codex Workflow Rules

When given a task:

1. Read `AGENTS.md`.
2. Inspect existing files before editing.
3. Make a short implementation plan.
4. Implement the smallest useful slice.
5. Preserve existing behavior.
6. Add tests where practical.
7. Update README/docs.
8. Run verification commands.
9. Summarize changed files and limitations.

Do not make broad rewrites.

Do not implement multiple major phases in one task unless explicitly asked.

Prefer small, reviewable commits.

---

## Recommended Build Phases

### Phase 1: Project Skeleton

- FastAPI backend
- React frontend
- SQLite DB
- seed ingestion from JSON
- paper browser
- README

### Phase 2: PDF Full-Text Ingestion

- local PDF parsing
- section/page-aware text extraction
- chunking
- extraction diagnostics
- paper detail page with extracted text status

### Phase 3: Search

- keyword search
- vector/semantic search
- search result page
- source snippets

### Phase 4: Citation-Grounded Q&A

- Ask TTLAB page
- retrieved chunks
- grounded answer
- citations
- no unsupported claims without warning

### Phase 5: Thesis Extension Finder

- student input form
- ranked paper recommendations
- extension ideas
- MVP/evaluation/risk output

### Phase 6: Summaries And Podcast Scripts

- public summary
- technical summary
- contribution/limitations/future work
- podcast script generator

### Phase 7: Topic/Author Explorer

- topics
- author pages
- paper-topic-author relationships
- simple graph/table visualization

### Phase 8: Evaluation Dashboard

- question set
- retrieval metrics
- review table
- exportable evaluation report

### Phase 9: Admin Review/Correction

- metadata editing
- topic editing
- generated-content review status
- correction persistence

### Phase 10: Polish And Demo

- UI cleanup
- demo dataset
- demo script
- deployment notes
- supervisor-ready presentation flow

---

## Definition Of Done

A task is done only when:

- the requested feature works locally,
- relevant tests/builds pass or limitations are documented,
- README/docs are updated,
- data contracts remain clear,
- AI outputs are source-grounded where required,
- no unrelated rewrites were introduced,
- the app remains demoable after the change.

---

## Final Product Standard

The final two-week project should be able to demonstrate:

1. Ingesting a few TTLAB full papers.
2. Searching across full-paper content.
3. Asking grounded questions with citations.
4. Viewing paper summaries and limitations.
5. Getting project/thesis extension recommendations.
6. Generating a podcast script.
7. Showing evaluation metrics.
8. Showing a polished public-facing interface.

The platform should make TTLAB research easier for the public, students, researchers, and industry partners to understand and use.
