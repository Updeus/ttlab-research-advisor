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

When RAG answers are implemented, extend the same evaluation set with answer points:

```json
{"question":"Which TTLAB papers discuss RAG?","gold_paper_ids":["..."],"answer_points":["..."]}
```

Minimum grounding review fields:

- cited source count
- citation correctness review status
- answer faithfulness score
- answer usefulness score

Do not claim retrieval or answer quality without evaluation evidence.
