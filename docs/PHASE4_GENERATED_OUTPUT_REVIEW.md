# Phase 4.3 Generated-Output Review

## Purpose and review boundary

This phase defines a deterministic audit for stored generated outputs, correction
of reproducible defects, and append-only review events. The currently retained
artifact was re-executed at source commit
`0d4b9bdcb657034beab5c288ab174983eb0760e3` against an isolated database
copy; it is not a projection of the current operational `data/papers.db`. The
reviewer identity is `codex-ai-review`, the reviewer type is `ai`, and the
distinct successful target state is `ai_reviewed`.

`ai_reviewed` is not human approval. It means that automated checks found current source locators, the expected output structure, and explicit boundaries between source-supported facts and generated suggestions. It does not establish novelty, complete semantic entailment, author agreement, supervisor suitability, feasibility, or user usefulness. Those claims require human assessment.

## Re-execution inventory and defect

The retained re-execution planned decisions for 48 generated records:

| Record type | Count | Re-execution treatment |
| --- | ---: | --- |
| RAG answers | 27 | Existing events for this review version were reused; target state `needs_reprocess` |
| Thesis recommendations | 7 | New review-version events were created; target state `ai_reviewed` |
| Paper artifacts, including bundles and podcast scripts | 14 | New review-version events were created; target state `ai_reviewed` |

The isolated input contained 48 review events before the target-copy apply. Of
the planned records, 27 RAG answers already had a matching
`phase4-generated-output-review-v1` event and were reused; the other 21 planned
records required a new version event. The review policy remains conservative:
a locator that no longer resolves cannot support a grounded claim, even if its
cached snippet appears plausible. An earlier repository revision recorded the
initial 48-created/48-changed live application; that archived execution is not
the current artifact and remains available in Git history rather than being
silently relabelled.

## Review method

The implementation is in `backend/app/evaluation/generated_output_review.py`. For each record, it:

1. checks that the database exposes reviewer attribution, a distinct review status, and append-only review-event fields;
2. resolves each paper, chunk, page range, section, and source hash against the current eligible corpus;
3. checks output-specific schema and suggestion-boundary requirements;
4. deterministically regenerates artifacts and recommendations when the stored request is sufficient to reproduce them;
5. preserves the record identifier while applying corrected content, grounding metadata, citations, provider metadata, and warnings;
6. records one hash-chained `ReviewEvent` containing the decision, rationale, checks, sanitized corrections, and cited evidence locators; and
7. refuses to label a record `ai_reviewed` when required evidence or structure is absent.

The repository schema was already compatible, so no migration was required. The compatibility check reports that `ai_reviewed` can be stored as a distinct string state and that review events are append-only.

## Decisions and corrections

| Record type | Decision | Count | Treatment |
| --- | --- | ---: | --- |
| RAG answers | `needs_reprocess` | 27 | Preserved for audit history; grounding corrected to `unsupported`; no answer text was silently replaced. |
| Thesis recommendations | `ai_reviewed` | 7 | Regenerated from the complete stored request with the current deterministic recommender and current chunks; identifiers preserved. |
| Paper artifacts | `ai_reviewed` | 14 | Regenerated from current source chunks with the existing deterministic generators; identifiers preserved. |

The RAG rows were not safely reproducible because they do not persist every original generation parameter, including the paper scope, audience, and answer-length limit. Reconstructing those values would invent provenance. Several rows also exhibited malformed concatenation or boundary defects. The safe action was therefore to retain all 27 records, mark them `needs_reprocess`, and require a new request through the current RAG workflow.

The 14 artifacts cover stored public and technical summaries, contribution, methods, limitations, future work, possible extensions, required skills, evaluation plans, bundles, and podcast scripts. The seven recommendations retain an explicit distinction among a gap stated by the paper, an inferred gap, no gap found, and a newly generated student-project suggestion.

## Recorded evidence

The source-commit-`0d4b9bdcb657034beab5c288ab174983eb0760e3` artifact records
48 planned decisions and 221 paper/chunk/page evidence locators. On the isolated target copy, the first pass
created 21 version events and changed the corresponding seven recommendations
and 14 artifacts; it reused the 27 existing RAG version events. Review-event
integrity verified the resulting 69-event chain with no invalid or
legacy-unverified events.

The disposable two-pass proof produced:

- first pass: 21 events created, 21 records changed, and 27 existing version
  events reused;
- second pass: zero events created, zero records changed, and all 48 planned
  reviews reused; and
- `live_database_mutated=false`.

The immediate second pass on the isolated target copy also created/changed
zero, skipped all 48 planned items, and re-verified all 69 events. The retained
manifest binds the database hashes before and after that isolated apply. It does
not claim that the current operational database was mutated or that its review
state equals the reproduction copy; current delivery state is reported by the
read-only evidence snapshot.

Sanitized, redistributable evidence is stored in `artifacts/phase4/generated_output_review/`:

- `generated_output_reviews.jsonl`: one sanitized decision per record;
- `generated_output_review_summary.json`: aggregate decisions, compatibility, apply counts, event integrity, and residual limitations;
- `idempotence_evidence.json`: the disposable two-pass proof; and
- `generated_output_review_manifest.json`: hashes for the code, database states, and evidence files.

Generated answer, recommendation, summary, and podcast bodies are not copied into these artifacts. Corrections are represented by before/after SHA-256 hashes and reasons; evidence contains source locators and snippet hashes rather than redistributed source text.

## Reproduction

From the repository root, an audit-only run performs the disposable proof
without applying decisions to the selected database. Use a separate output
directory when checking the retained evidence:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review \
  --output-dir /tmp/ttlab-generated-output-review-audit
```

To exercise the apply path, point it at an explicitly prepared disposable
database copy and a separate output directory:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review \
  --database /tmp/ttlab-generated-output-review.db \
  --output-dir /tmp/ttlab-generated-output-review-apply \
  --apply-live
```

Do not use `--apply-live` against the operational database merely to reproduce
the manuscript evidence.

Focused tests:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_generated_output_review.py -q
```

The apply operation is version-idempotent. A repeated run recognizes the existing `phase4-generated-output-review-v1` events, verifies status consistency, creates no duplicate events, and makes no further record changes.

## Residual limitations and required human work

- The 27 historical RAG answers must be regenerated from new user requests before presentation as reviewed answers.
- Locator, schema, lexical, and deterministic verifier checks do not prove that every sentence is semantically entailed by its sources.
- Recommendation novelty, project duration, data access, researcher fit, and supervisor suitability require human confirmation.
- Summary usefulness, podcast clarity, and recommendation usefulness have not been established by a user study.
- Author or supervisor approval is an external attestation and is not inferred
  from this AI review; see `docs/EXTERNAL_SUBMISSION_CHECKS.md`.
