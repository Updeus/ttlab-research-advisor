# Evaluation Plan

## Phase 1

Evaluation is limited to ingestion correctness and API availability.

Automated checks:

- TTLAB archive fixture parsing extracts title, authors, venue, raw date, source URL, PDF URL, pagination, and audit URLs.
- Duplicate titles are deduplicated.
- Split years such as `March, 202 6` are safely parsed as `2026`.
- Seed JSON imports into SQLite.
- `/health` and `/api/papers` return expected responses.

## Phase 3 Retrieval Evaluation

Create a manually reviewed `data/evaluation/questions.jsonl` before reporting retrieval quality:

```json
{"question":"Which TTLAB papers discuss RAG?","gold_paper_ids":["..."],"notes":"Manually reviewed gold papers."}
```

Run:

```bash
PYTHONPATH=backend python -m app.evaluation.retrieval_eval \
  --questions data/evaluation/questions.jsonl \
  --mode hybrid \
  --top-k 5
```

The committed `data/evaluation/questions.sample.jsonl` is a template only and intentionally has empty labels. The evaluation CLI fails clearly when gold labels are empty.

Metrics:

- Recall@3
- Recall@5
- MRR
- number of questions
- per-question retrieved paper IDs

## Later MVP Phases

## Phase 4 QA Evaluation

Create a manually reviewed `data/evaluation/qa_questions.jsonl` before reporting answer quality:

```json
{"question":"Which indexed papers discuss RAG?","gold_paper_ids":["..."],"required_answer_points":["..."],"notes":"Manually reviewed later."}
```

Run:

```bash
PYTHONPATH=backend python -m app.evaluation.qa_eval \
  --questions data/evaluation/qa_questions.jsonl \
  --mode hybrid \
  --top-k 5
```

The committed `data/evaluation/qa_questions.sample.jsonl` is a template only and intentionally has empty labels. The QA CLI fails clearly when gold labels are empty.

Minimum grounding review fields:

- cited source count
- citation correctness review status
- answer faithfulness score
- answer usefulness score

Do not claim retrieval or answer quality without evaluation evidence.

## Phase 5 Extension Recommendation Evaluation

Create or edit `data/evaluation/extension_eval_cases.jsonl` before reporting recommendation quality:

```json
{"case_id":"sample-001","interests":"RAG and web apps","skills":["Python","React","FastAPI"],"available_time":"semester","project_type":"software prototype","data_constraints":"public or synthetic data","preferred_difficulty":"medium","expected_relevant_topics":["RAG","research discovery"],"notes":"Placeholder only; replace with manually reviewed cases."}
```

Run:

```bash
PYTHONPATH=backend python -m app.evaluation.extension_eval \
  --cases data/evaluation/extension_eval_cases.jsonl \
  --top-k 5
```

Output:

```text
data/evaluation/extension_eval_results.json
```

Automated metrics:

- recommendation_count
- citation_count
- cited_paper_count
- grounding_status
- percentage_recommendations_with_citations
- warnings_count

Human review template:

```text
data/evaluation/extension_human_review_template.csv
```

Human fields are intentionally blank until reviewed:

- relevance_score
- feasibility_score
- usefulness_score
- grounding_score
- risk_appropriateness
- reviewer_notes

The extension evaluator measures citation coverage and grounding signals only. It does not prove that a project is novel, supervisor-approved, or feasible without human review.

## Phase 6 Paper Artifact Evaluation

Create or edit `data/evaluation/artifact_eval_cases.jsonl` before reporting artifact quality:

```json
{"case_id":"sample-001","paper_id":"...","artifact_types":["public_summary","technical_summary","limitations","future_work"],"expected_source_chunk_ids":[],"notes":"Placeholder only; replace with manually reviewed cases."}
```

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval \
  --cases data/evaluation/artifact_eval_cases.jsonl
```

Output:

```text
data/evaluation/artifact_eval_results.json
```

Automated metrics:

- artifact_count
- citation_count
- percentage_artifacts_with_citations
- grounding_status
- warnings_count
- sections_with_explicit_support
- sections_inferred
- sections_not_found

Human review template:

```text
data/evaluation/artifact_human_review_template.csv
```

Human fields are intentionally blank until reviewed:

- accuracy_score
- faithfulness_score
- readability_score
- usefulness_score
- citation_correct
- reviewer_notes

The artifact evaluator measures citation coverage, grounding status, and support-status counts only. It does not prove correctness, readability, public suitability, or podcast readiness without human review.

## Phase 7 Admin Review And Evaluation Dashboard

Phase 7 does not add new quality claims. It adds a local/demo workflow for reviewing the records produced by earlier phases and a read-only dashboard for showing which evaluation evidence exists.

Admin review can capture:

- paper metadata corrections,
- paper artifact review status and optional corrected text/JSON,
- Thesis Extension Finder review status and optional corrected recommendation JSON,
- Ask TTLAB citation correctness,
- Ask TTLAB faithfulness and usefulness scores from 1-5,
- extraction review notes such as acceptable, rejected, or needs reprocess.

Every review action creates a `ReviewEvent` with previous/new status, reviewer notes, and optional field diffs. These events are an audit trail for demo review. They are not an authenticated production workflow.

Review statuses:

- `needs_review`: imported or generated item has not been checked.
- `reviewed`: checked but not formally approved.
- `approved`: acceptable for demo use.
- `rejected`: should not be used as-is.
- `needs_reprocess`: should be rerun or manually inspected.

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

The Evaluation Dashboard reads these files when present:

- `data/evaluation/retrieval_eval_results.json`
- `data/evaluation/qa_eval_results.json`
- `data/evaluation/extension_eval_results.json`
- `data/evaluation/artifact_eval_results.json`

If a file is missing, the dashboard returns `status = "not_run"` and shows no metric. It does not invent scores from database contents.

The dashboard also displays whether human review templates are available:

- `data/evaluation/extension_human_review_template.csv`
- `data/evaluation/artifact_human_review_template.csv`

Evaluation remains academically responsible only if gold labels and human scores are manually reviewed. Placeholder sample files should never be presented as performance evidence.

## Phase 8 Topic/Author Explorer Evaluation

Phase 8 does not add generated research claims. It adds deterministic relationship data and demo polish, so evaluation focuses on coverage, traceability, and review readiness.

Automated checks:

- topic normalization merges obvious synonyms such as `RAG` and `retrieval augmented generation`;
- topic rebuild creates topics from paper metadata, chunks, and generated artifacts;
- reviewed/manual paper topics are not overwritten by inferred topics;
- author-topic aggregation counts papers and top topics correctly;
- related-paper scoring returns reasons such as shared topic and shared author;
- explorer APIs return overview, topic, author, and related-paper data;
- `/api/stats` includes topic and author metrics.

Manual review questions for demos:

- Are the top topics useful enough for navigation?
- Does the evidence explain why a topic was assigned?
- Are author expertise summaries clearly labeled as derived from indexed papers?
- Do related-paper reasons help a student find nearby work?
- Are reviewed/corrected topics preserved after rebuild?

There is no claimed precision/recall for topic labels yet. Topic labels are deterministic/inferred unless reviewed, and the explorer intentionally avoids a complex graph visualization in this MVP.

## Placeholder File Clarity

Files ending in `.sample.jsonl` are templates only. Existing extension and artifact case files are demo scaffolds unless their notes and expected values have been manually reviewed.

Do not invent gold labels, expected source chunks, or human scores. For thesis evaluation, add supervisor/manual review where time allows:

- fill `gold_paper_ids` for retrieval and QA cases;
- fill required answer points for QA;
- replace placeholder extension cases with reviewed student-profile cases;
- replace placeholder artifact cases with reviewed expected chunks;
- fill human review CSV templates only after a reviewer scores the outputs.

Automatic metrics measure only against the files provided. They are useful for reproducibility and regression checks, but they are not a claim of research quality without reviewed test cases.

## Local Ollama Benchmarking

Local model benchmarking is machine-specific and should be treated as an optimization baseline, not a research-quality claim.

Run:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.ollama_benchmark --models installed
```

Outputs:

- `data/evaluation/ollama_benchmark_results.json`
- `data/evaluation/ollama_benchmark_results.csv`

The benchmark records first/warm response time, tokens per second when Ollama reports it, citation compliance, refusal behavior, and a simple heuristic answer-quality score. Human review is still required before claiming that one model is academically better than another.
