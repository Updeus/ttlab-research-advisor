# Evaluation Plan

## Phase 1

Evaluation is limited to ingestion correctness and API availability.

Automated checks:

- TTLAB archive fixture parsing extracts title, authors, venue, raw date, source URL, PDF URL, pagination, and audit URLs.
- Duplicate titles are deduplicated.
- Split years such as `March, 202 6` are safely parsed as `2026`.
- Seed JSON imports into SQLite.
- `/health` and `/api/papers` return expected responses.

## Later MVP Phases

When search and RAG are implemented, add `data/evaluation/questions.jsonl` with:

```json
{"question":"Which TTLAB papers discuss RAG?","gold_paper_ids":["..."],"answer_points":["..."]}
```

Minimum retrieval metrics:

- Recall@3
- Recall@5
- MRR

Minimum grounding review fields:

- cited source count
- citation correctness review status
- answer faithfulness score
- answer usefulness score

Do not claim retrieval or answer quality without evaluation evidence.
