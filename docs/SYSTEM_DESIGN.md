# System Design

## Backend

The backend is a FastAPI application under `backend/app`.

- `main.py` creates the app, CORS policy, startup table creation, and health endpoint.
- `db.py` configures SQLite and SQLModel sessions.
- `models/` defines `Paper`, `Author`, `Chunk`, `RAGAnswer`, `ThesisRecommendation`, `PaperArtifact`, `ReviewEvent`, `Topic`, `PaperTopic`, and `AuthorTopic`.
- `api/papers.py` exposes paper, stats, extraction, chunk, and simple chunk keyword endpoints.
- `api/admin.py` exposes local/demo review overview, mixed review queue, review/correction actions, extraction review, and audit events.
- `api/evaluation.py` exposes the read-only evaluation dashboard.
- `api/explorer.py` exposes topic, author, explorer overview, and related-paper endpoints.
- `ingestion/ttlab_page.py` discovers TTLAB archive records.
- `ingestion/manual_import.py` imports seed JSON into SQLite.
- `ingestion/pdf_downloader.py` safely downloads direct PDFs only when `--download` is passed.
- `ingestion/pdf_parser.py` extracts PDF text page-by-page using PyMuPDF.
- `indexing/chunker.py` creates deterministic page-aware source chunks from extracted text.
- `indexing/keyword_search.py` creates/searches a SQLite FTS5 keyword index, with deterministic fallback matching.
- `indexing/embedder.py` builds local hashing embeddings without API keys or model downloads.
- `indexing/vector_store.py` loads local embedding JSON and performs cosine search.
- `indexing/retriever.py` combines keyword and semantic results for hybrid retrieval.
- `intelligence/llm_provider.py` defines the offline extractive provider and optional external-provider adapter boundary.
- `intelligence/rag_answerer.py` retrieves chunks, drafts an answer, verifies citations, and stores answers.
- `intelligence/citation_verifier.py` checks citation presence and lightweight lexical support.
- `intelligence/extension_recommender.py` retrieves chunks, groups candidate papers, scores them, creates deterministic thesis extension suggestions, verifies them, and stores recommendation runs.
- `intelligence/recommendation_verifier.py` checks recommendation citations, retrieved chunk mappings, gap support status, data warnings, skills gaps, and timeline risk.
- `intelligence/paper_artifact_generator.py` selects section-aware source chunks, creates deterministic paper intelligence artifacts, stores them, writes local generated JSON, and exposes CLI commands.
- `intelligence/podcast_script_generator.py` generates text-only podcast script drafts from paper intelligence bundles and cited chunks.
- `intelligence/artifact_verifier.py` checks artifact citations, support statuses, extraction warnings, source chunk mapping, and grounding status.
- `intelligence/topic_explorer.py` deterministically normalizes topics, creates paper-topic and author-topic links, derives author expertise summaries, and scores related papers.
- `evaluation/retrieval_eval.py` calculates Recall@3, Recall@5, and MRR from manually reviewed gold paper IDs.
- `evaluation/qa_eval.py` runs Ask TTLAB and records citation/grounding outputs against manually reviewed labels.
- `evaluation/extension_eval.py` measures recommendation count, citation coverage, cited paper count, grounding status, and warnings from manually reviewed cases.
- `evaluation/artifact_eval.py` measures artifact citation coverage, support statuses, grounding status, and warnings from manually reviewed cases.
- `evaluation/dashboard.py` parses existing evaluation result JSON and summarizes quality/review status without inventing missing metrics.
- `evaluation/run_all.py` optionally attempts the evaluation CLIs and records a local run summary.

## Data Flow

```text
TTLAB WordPress archive
  -> discovery CLI
  -> data/seed/ttlab_publications_discovered.json
  -> data/seed/papers.json
  -> manual import CLI
  -> SQLite
  -> PDF downloader
  -> data/pdfs/{paper_id}.pdf
  -> PDF parser
  -> data/extracted_text/{paper_id}.json + .txt
  -> deterministic chunker
  -> data/chunks/{paper_id}.json + SQLite chunk rows
  -> keyword index + hashing vector index
  -> retrieval API
  -> Ask TTLAB answerer + citation verifier
  -> Thesis Extension Finder + recommendation verifier
  -> paper artifact generator + artifact verifier
  -> local admin review events
  -> deterministic topic/author explorer links
  -> FastAPI
  -> React dashboard/browser/detail/search/Ask/Thesis Extension Finder/Paper Intelligence/Topic-Author Explorer/Admin/Evaluation views
```

## Discovery Contract

Each discovered record includes:

```text
paper_id, title, authors, year, publication_date_raw, venue,
post_url, source_url, pdf_url, local_pdf_path, topics, all_urls,
ingestion_status, pdf_text_status, review_status, raw_scraped
```

The scraper resolves relative URLs, deduplicates by normalized title and URLs, preserves raw scraped paragraphs/links, and does not follow external publisher pages.

## Extraction Contract

Each extraction JSON includes:

```text
paper_id, local_pdf_path, page_count, pages[], full_text_path,
text_hash, extraction_status, warnings, diagnostics
```

Diagnostics include page/word/character counts, pages with and without text, possible scanned-PDF detection, and extraction errors.

## Chunk Contract

Each chunk includes:

```text
chunk_id, paper_id, chunk_index, page_start, page_end, section,
text, char_count, word_count, token_count_estimate, source_hash
```

Chunks are deterministic, page-aware, overlap by roughly 100-150 words, and use simple heading rules for section labels.

## Retrieval Contract

Retrieval returns source chunks only:

```text
rank, paper_id, paper_title, authors, year, chunk_id,
section, page_start, page_end, snippet, scores, source
```

Modes:

- `keyword`: SQLite FTS5 if available; fallback token matching otherwise.
- `semantic`: local hashing embeddings stored under `data/indexes/`.
- `hybrid`: normalized keyword and semantic score combination.

Phase 3 retrieval does not call an LLM and does not generate answers.

## Ask Contract

Ask TTLAB returns stored, source-cited answer drafts:

```text
answer_id, question, answer, grounding_status, provider, model,
retrieval_mode, citations[], retrieved_chunks[], warnings[], created_at
```

Grounding status:

- `grounded`: citations map to retrieved chunks and the answer overlaps with cited snippets.
- `partial`: some support exists but citations or overlap are weak.
- `unsupported`: no useful retrieved/cited support exists.

The default provider is `offline_extractive`, which works without API keys by extracting relevant sentences from retrieved chunks. Optional external providers must be adapter-based and must not break offline operation.

## Thesis Extension Finder Contract

Extension runs are stored in SQLite as `ThesisRecommendation` records:

```text
recommendation_id, request_json, student_interests_json,
student_skills_json, available_time, project_type, data_constraints,
preferred_difficulty, recommendations_json, provider, model,
retrieval_mode, top_k, grounding_status, warnings_json, created_at
```

Each recommendation inside `recommendations_json` includes:

```text
rank, paper_id, paper_title, authors, year, fit_score,
paper_focus, source_supported_facts, identified_gap,
extension_title, extension_summary, why_it_fits_student,
mvp_scope, stretch_goals, required_skills, skills_gap,
data_required, data_availability, evaluation_plan,
difficulty, risk_level, implementation_time, related_papers,
potential_researcher_fit, citations, warnings
```

The finder is not a chat system. It is a structured research advisor flow:

1. Build a retrieval query from interests, preferred topics, project type, and data constraints.
2. Retrieve source chunks through the existing keyword/semantic/hybrid retriever.
3. Group chunks by `paper_id`.
4. Score each paper with deterministic weights:
   - retrieval relevance: 0.30
   - interest/topic match: 0.20
   - skill match: 0.15
   - data feasibility: 0.10
   - timeline feasibility: 0.10
   - difficulty match: 0.10
   - evidence strength: 0.05
5. Generate an offline template recommendation from title, authors, source facts, and retrieved snippets.
6. Verify citations and gap support status before persisting.

Grounding status:

- `grounded`: every recommendation has citations, source facts map to retrieved chunks, and gap evidence is explicit.
- `partial`: citations exist, but a gap is inferred or not found, or some evidence is weak.
- `unsupported`: no cited retrieved chunks support the recommendations.

Potential researcher fit is based only on paper authorship and is explicitly not a confirmed supervisor claim.

## Paper Intelligence Artifact Contract

Paper-level intelligence outputs are stored as `PaperArtifact` records:

```text
artifact_id, paper_id, artifact_type, generated_json, generated_text,
source_chunk_ids_json, citations_json, provider, model,
generation_status, grounding_status, review_status, warnings_json,
created_at, updated_at
```

Supported `artifact_type` values:

```text
public_summary, technical_summary, contribution, methods,
limitations, future_work, possible_extensions, required_skills,
evaluation_plan, podcast_script, paper_intelligence_bundle
```

The `paper_intelligence_bundle` payload contains:

```text
paper_id, paper_title, authors, year, generated_notice,
public_summary, technical_summary, contribution, methods,
limitations, future_work, possible_extensions, required_skills,
evaluation_plan, warnings, review_status
```

Artifact generation flow:

1. Load paper metadata and chunks.
2. Prefer chunks whose sections look like Abstract, Introduction, Methodology, Results, Discussion, Limitations, Future Work, or Conclusion.
3. Fall back to keyword scoring for terms such as contribution, propose, method, approach, result, limitation, future work, evaluation, and dataset.
4. Generate deterministic extractive/template sections offline.
5. Mark limitations and future work as `explicit`, `inferred`, or `not_found`.
6. Mark possible extensions as `suggested_by_system`.
7. Verify citations against real chunk IDs.
8. Persist SQLite artifacts and write ignored local JSON under `data/generated/paper_artifacts/`.

Grounding status:

- `grounded`: cited chunks support the generated artifact and no weak/missing section warnings apply.
- `partial`: some sections are inferred, suggested by the system, or weakly cited.
- `unsupported`: no usable citations are available.

All artifacts default to `review_status = "needs_review"`. The paper detail UI displays artifacts, citations, support status, and review status. The Phase 7 Admin Review UI can approve, reject, return to needs review, add notes, or store corrected text for local demo review.

Podcast scripts are text-only. The script payload includes episode title, description, target duration, Host and Research Explainer dialogue, cited source papers, citations, warnings, and `review_status = "needs_review"`.

## Admin Review Contract

Phase 7 is local/demo administration only. There is no authentication or role-based access control.

Reviewable records normalize these fields where practical:

```text
review_status, reviewer_notes, reviewed_at, reviewed_by
```

Supported statuses:

```text
needs_review, reviewed, approved, rejected, needs_reprocess
```

`ReviewEvent` records capture:

```text
review_event_id, item_type, item_id, action, previous_status,
new_status, reviewer_name, reviewer_notes, diff_json, created_at
```

Actions include:

```text
reviewed, approved, rejected, corrected,
marked_needs_review, marked_needs_reprocess
```

Review APIs:

- paper metadata patches update only provided fields and preserve raw/source data.
- artifact review updates review status, notes, optional corrected text, and optional corrected JSON.
- thesis recommendation review updates review status, notes, and optional corrected recommendation JSON.
- Ask answer review stores citation correctness plus optional 1-5 faithfulness/usefulness scores.
- extraction review uses paper review metadata to mark extraction as approved, rejected, or needing reprocess.

Every review/correction action creates a `ReviewEvent`. This is an audit trail for a local demo, not a production publishing workflow.

## Evaluation Dashboard Contract

`evaluation/dashboard.py` reads existing result files under `data/evaluation/`:

```text
retrieval_eval_results.json
qa_eval_results.json
extension_eval_results.json
artifact_eval_results.json
```

If a result file is absent, the API returns `status = "not_run"`. If present, it parses only fields generated by the corresponding evaluator:

- retrieval: question count, Recall@3, Recall@5, MRR.
- QA: question/answer count, citation count, cited gold paper count, grounding counts.
- extension: case count, recommendation count, citation coverage, grounding counts, warning count.
- artifact: case/artifact count, citation coverage, grounding counts, explicit/inferred/not-found section counts.

The dashboard also reports human review template availability and database quality counts such as indexed chunks, generated artifacts, and items still needing review. It is read-only and must not invent quality claims.

## Topic/Author Explorer Contract

Phase 8 adds normalized topic and author relationship tables:

```text
Topic(topic_id, name, normalized_name, description, source, review_status, created_at, updated_at)
PaperTopic(link_id, paper_id, topic_id, score, evidence_json, source, created_at)
AuthorTopic(link_id, author_id, topic_id, paper_count, score, evidence_json, created_at)
```

Topic assignment is deterministic. Sources include:

- `paper.topics` and `paper.keywords`,
- paper title and venue text,
- chunk section labels and chunk text,
- generated paper artifacts such as required skills, possible extensions, technical summaries, and contribution fields,
- reviewed/corrected metadata where available.

Normalization is intentionally small and inspectable. It lowercases and title-cases labels, then merges obvious variants such as:

- `rag` / `retrieval augmented generation`
- `ai` / `artificial intelligence`
- `ml` / `machine learning`
- `iot` / `internet of things`
- `optimisation` / `optimization`

Reviewed or approved `Paper.topics` are treated as the source of truth for that paper during rebuilds. The rebuild command does not overwrite those reviewed topics; it only recreates explorer link rows. Evidence is preserved on each `PaperTopic` link so the UI can show why a topic was assigned.

Author profiles are aggregated from indexed authorship, linked topics, recent papers, coauthors, venues, and generated artifact counts. The potential expertise summary is deterministic and uses wording such as "potential researcher fit based on authorship and indexed paper topics"; it never claims a person is a confirmed supervisor.

Related papers are scored with simple, explainable signals:

- shared authors,
- shared normalized topics,
- shared venue,
- nearby publication year,
- shared metadata/title keywords,
- local hashing semantic retrieval similarity when an index exists.

Explorer APIs:

- `GET /api/explorer/overview`
- `GET /api/topics`
- `GET /api/topics/{topic_id}`
- `GET /api/authors`
- `GET /api/authors/{author_id}`
- `GET /api/papers/{paper_id}/related`

The frontend uses card/table layouts rather than a graph library. Empty states tell the user to run:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
```

## Future Extension Points

- `indexing/` can later add production embedding providers and vector-store adapters behind the existing provider interfaces.
- `intelligence/` can later add production answer providers and external generation providers behind the existing adapter boundaries.
- `evaluation/` will hold retrieval, QA, artifact, and later human review modules.
