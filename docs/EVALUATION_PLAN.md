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
