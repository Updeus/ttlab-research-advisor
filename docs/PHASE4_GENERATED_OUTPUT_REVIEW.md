# Phase 4.3 Generated-Output Review

## Purpose and review boundary

This phase audits every generated output currently stored in `data/papers.db`, corrects reproducible defects, and records an append-only review event. The reviewer identity is `codex-ai-review`, the reviewer type is `ai`, and the distinct successful state is `ai_reviewed`.

`ai_reviewed` is not human approval. It means that automated checks found current source locators, the expected output structure, and explicit boundaries between source-supported facts and generated suggestions. It does not establish novelty, complete semantic entailment, author agreement, supervisor suitability, feasibility, or user usefulness. Those claims require human assessment.

## Pre-review inventory and defect

The live inventory contained 48 generated records:

| Record type | Count | Initial review state |
| --- | ---: | --- |
| RAG answers | 27 | `needs_review` |
| Thesis recommendations | 7 | `needs_review` |
| Paper artifacts, including bundles and podcast scripts | 14 | `needs_review` |

There were no review events before this pass. All stored generated-output citation locators referenced chunk identifiers from the earlier chunking run and did not resolve against the current eligible corpus. A locator that no longer resolves cannot support a grounded claim, even if its cached snippet appears plausible.

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

The completed live apply created 48 review events and corrected 48 records. The events contain 269 paper/chunk/page evidence locators. Review-event integrity verified all 48 events with no invalid or legacy-unverified events.

The disposable database proof produced:

- first pass: 48 events created and 48 records changed;
- second pass: zero events created, zero records changed, and all 48 existing reviews reused; and
- no mutation of the live database during the proof.

After the proof passed, the live apply produced the same 48 decisions. Its immediate second pass created zero events, changed zero records, reused all 48 reviews, and re-verified the event chain. The pre-apply private SQLite backup passed `PRAGMA quick_check`; its logical SQL dump SHA-256 matched the source dump (`dfc073787b79a1c75834644ad64672c5d9c9fe002605668271254e420e84e09e`). The post-apply database passed `PRAGMA quick_check` and returned no foreign-key violations. The repository smoke check reported 17 passes, zero warnings, zero failures, and overall `PASS`.

Sanitized, redistributable evidence is stored in `artifacts/phase4/generated_output_review/`:

- `generated_output_reviews.jsonl`: one sanitized decision per record;
- `generated_output_review_summary.json`: aggregate decisions, compatibility, apply counts, event integrity, and residual limitations;
- `idempotence_evidence.json`: the disposable two-pass proof; and
- `generated_output_review_manifest.json`: hashes for the code, database states, and evidence files.

Generated answer, recommendation, summary, and podcast bodies are not copied into these artifacts. Corrections are represented by before/after SHA-256 hashes and reasons; evidence contains source locators and snippet hashes rather than redistributed source text.

## Reproduction

From the repository root, an audit-only run performs the disposable proof and writes evidence without changing the live database:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review
```

To apply the review after the built-in disposable proof succeeds:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review --apply-live
```

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
- Author or supervisor approval remains **AUTHOR INPUT REQUIRED**.
