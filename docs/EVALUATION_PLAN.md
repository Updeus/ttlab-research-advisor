# Evaluation Plan and Execution Status

## Managed-profile reevaluation

PostgreSQL `ts_rank_cd` does not reproduce SQLite FTS5 BM25 ordering, so retrieval and QA evaluation must be rerun against the imported managed corpus. Gemini composition and GCP load behavior are separate unvalidated conditions: do not transfer local/Ollama findings or claim quality/scalability until held-out QA, citation review, restart/scale persistence, and load tests are recorded. Retain all negative results and forced-provider-failure fallback evidence.

This document is the concise plan/status view. Metric definitions, confidence
interval procedures, exact results, and evidence paths are in
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md). The research design is in
[`METHODOLOGY.md`](METHODOLOGY.md).

## Evaluation principles

- Freeze corpus eligibility and representation manifests before quality runs.
- Use source-derived AI-reviewed silver labels with `reviewer_type=ai`; do not
  relabel them as human gold or independent review.
- Split development and held-out test cases before tuning.
- Compare all retrieval modes on identical corpus/query/filter/cutoff controls.
- Preserve raw cases, rankings, configurations, hashes, seeds, and failures.
- Name set Recall, Hit, Precision, MRR, and nDCG correctly and separately.
- Report uncertainty and paired comparisons where sample structure supports it.
- Keep engineering tests, inventory, traceability, and quality metrics distinct.
- Treat `not_run` and unavailable providers as missing evidence, never zero or
  success.
- Publish negative findings and residual limitations.
- Keep the immutable audit-baseline v1 results labeled as audit evidence and
  separate from both the post-remediation v1-form re-execution and the
  prospectively frozen v2 remediation protocol.

## Evidence-revision boundary

The current manuscript measurements are the exact post-remediation
re-execution of the v1-form protocols at commit
`73092e48f173b74f726659bd5b98224545ac23bb` against technical snapshot
`corpus-f4638c633bea82b0` (snapshot hash
`f4638c633bea82b02df4e6ff5f8540020f3ca29bd7493a3465036a37582c7ab1`).
They are descriptive AI-assisted offline evidence, not a paired before/after
experiment. The independent-audit baseline at
`b561fa73c1de50569d7e76261b2aa37195524c21` and
`corpus-04a010207327069a` remains preserved below for audit traceability, but
it is not the evidence consumed by the current paper or thesis.

## RQ-to-evaluation map

| RQ | Evaluation | Status | Decision supported |
|---|---|---|---|
| RQ1 corpus/traceability | eligibility/PDF identity audit, section silver review, manifest one-to-one coverage | Post-remediation v1-form executed | 96 papers/719 chunks form the current frozen technical corpus; two mismatches and 36 no-text records remain excluded |
| RQ2 retrieval | keyword, feature-hashing, dense, heuristic/tuned hybrid; dev tuning; test; ablation/sensitivity/statistics | Post-remediation v1-form executed | keyword remains the strongest held-out MRR baseline; tuned hybrid superiority is not established |
| RQ3 RAG | atomic claim, citation-link, completeness, answer-point, unsupported knowledge, abstention review | Post-remediation v1-form executed | returned-citation utilization reached 1.0, but correctness, answer completeness, and abstention remain limited |
| RQ4 advisory/discovery | evidence-only vs full Finder, topic lexical-vs-dense, author audit, full stored-output review | Post-remediation v1-form executed | full-Finder improvement was not demonstrated; 17 baseline-ranked items had no full-Finder counterpart, and publication evidence/AI-review boundaries remain visible |
| RQ5 engineering readiness | backend/frontend/security/accessibility tests, performance, reproduction, release scan, PDF preflight | Historical performance and compliant manuscript builds exist; the source candidate is accepted only by its retained full gate | engineering and format evidence is revision-bound; reproduction/release must identify the executed source-candidate commit/tree separately from the later evidence commit and cannot establish effectiveness |
| Remediation-v2 selective response/Finder/topic/OCR | source-first frozen cases, fixed technical-scope execution, two shuffled passes of one AI procedure, seeded cluster bootstrap, exact package validation | Prospectively frozen, executed, and package-validated; result status is authoritative only in `artifacts/peer_review_remediation/v2/manifest_v2.json` plus its validation attestation | measures held-out selective-response behaviour and deterministic contracts without claiming public-projection quality, entailment, human usefulness, or corpus OCR accuracy |

## Current post-remediation v1-form datasets

All results in this section are AI-assisted offline evidence generated at
`73092e48...`/`corpus-f4638c633bea82b0`. They describe the current manuscript
v1-form evidence boundary, not the separately prospectively frozen v2 outcome
or anonymous public projection.

### Section quality

- 40 source-backed AI-reviewed chunks.
- Current v1-form output: overall accuracy 0.900; labeled accuracy 0.8889; labeled
  coverage 0.900; macro precision 0.8917; macro recall 0.9040.
- `Unknown` remains an allowed label.
- Evidence: `data/evaluation/section_quality_silver_v1.jsonl` and
  `artifacts/phase1/phase1_evidence.json`.

### Retrieval

- 50 source-derived questions: 30 development, 20 held-out test.
- Eleven strata including factual, method, result, metadata, comparison,
  synthesis, hard-negative, and out-of-corpus cases.
- Modes: keyword, 256-dimensional feature hashing, pinned 384-dimensional
  learned dense, heuristic hybrid, and development-tuned hybrid.
- Controls: 150-chunk component pools, retrieval depth 50, top 10 unique papers,
  same frozen candidate pools, no test tuning.
- Statistics: 10,000 query bootstraps, two-sided paired randomization, Holm-
  Bonferroni family correction.
- Result: keyword held-out MRR 0.947368; dense 0.938596; tuned hybrid 0.912281;
  no family-corrected contrast rejected the null.
- Evidence: `data/evaluation/retrieval_silver_v1.jsonl` and
  `artifacts/phase2/retrieval/`.

### RAG claim/citation review

- 50 cases: 46 answerable, four unanswerable.
- 334 checkable claims (331 supported, three partial, none unsupported) and 81
  answer points.
- Metrics: strict/weighted claim support, citation correctness, citation and
  correct-citation completeness, answer-point coverage, unsupported knowledge,
  answerability/abstention, category results, and errors.
- Result: citation correctness 0.652695; returned-citation utilization 1.000000; strict
  answer-point coverage 11/81 = 0.135802; unanswerable abstention 1/4.
- Optional Ollama comparison was not run because the service was unavailable.
- Evidence: `data/evaluation/qa_faithfulness_*` and
  `artifacts/phase3/qa/`.

### Recommendation proxy comparison

- 28 synthetic profiles; the evidence-only arm returned 84 ranked items and the
  full Finder returned 67, leaving 17 missing full-Finder counterparts.
- Two fixed-seed shuffled passes by the same AI procedure.
- Criteria: relevance, source fidelity, fact/future/gap/suggestion separation,
  novelty caution, feasibility, MVP/stretch, risk, skills, evaluation plan, and
  usefulness as an AI proxy.
- Result: zero-filled full-minus-evidence-only relevance -0.035714 (95% CI
  -0.119048 to 0.047619); improvement was not demonstrated. Feasibility and
  usefulness failed for all 67 returned full-Finder items.
- Twenty-two configurations (the default plus 21 zero/plus/minus-25% one-term
  perturbations) are retained; this is sensitivity analysis, not learned
  tuning.
- Evidence: `data/evaluation/recommendation_profiles_v1.jsonl` and
  `artifacts/phase4/recommendation_proxy_v1/`.

### Conversational idea-generation regression set

- `data/evaluation/idea_generation_cases_v1.jsonl` contains four formative
  prompts covering a likely paper match, agriculture, an out-of-corpus interest,
  and a multi-turn scope refinement.
- Review checks cover always returning one to three ideas, valid/absent citations
  as appropriate, fact-versus-suggestion separation, bounded MVPs, actionable
  evaluation, and novelty/supervision caution.
- This is regression scaffolding, not a gold dataset or evidence that students
  find the ideas useful. Live model outputs require a pinned Ollama digest and
  separate human/supervisor review before any effectiveness claim.

### Audit-baseline evidence retained

The independent audit at `b561fa73...`/`corpus-04a010207327069a` recorded a
tuned-hybrid MRR of 0.8596; 400 QA claims with citation correctness 0.625,
returned-citation utilization 0.592, strict answer-point coverage 0.1358, and 0/4
unanswerable abstentions; and a conditional 84-versus-84 Finder comparison
whose full-minus-evidence-only relevance was 0.0238 (95% CI -0.0238 to
0.0714). Those values remain negative audit-baseline evidence. They are not
silently substituted for the post-remediation measurements above.

### Topic and author evaluation

- 60 eligible papers: 36 development, 24 test; 39 labels; 51 multi-label; four
  `other/unknown`.
- Held-out controlled lexical precision/recall/F1: 0.6522/0.4839/0.5556.
- Held-out dense-prototype precision/recall/F1: 0.4175/0.6935/0.5212.
- The lexical path is retained for inspectability and higher precision; dense
  output is a review-candidate signal only.
- Author audit checks eligibility leakage, aliases, authorship, and prohibited
  availability/endorsement/expertise wording. Thirteen possible merges remain
  unresolved.
- Evidence: `data/evaluation/topic_author_silver_v1*` and
  `artifacts/phase4/topic_author/`.

### Generated-output review

- All 48 persisted outputs inspected: 27 historical RAG answers, seven thesis
  recommendations, and 14 paper artifacts.
- The retained re-execution is bound to source commit
  `0d4b9bdcb657034beab5c288ab174983eb0760e3`. On its
  isolated database copy it created 21 new versioned events and changed the 21
  artifacts/recommendations, reused 27 existing RAG version events, and
  verified the resulting 69-event chain. The second pass created/changed zero,
  skipped all 48 items, and `live_database_mutated=false` in the disposable
  proof.
- The review checks source locators, structure, and suggestion boundaries. It is
  not author/supervisor approval or a semantic entailment proof.
- Evidence: `artifacts/phase4/generated_output_review/`.

### External sanity and performance

- The external sanity procedure reacquired three pinned CC BY JATS XML
  documents and mapped them into the production chunker contract; all three
  fixed lexical queries returned the intended document at rank one. This checks
  a narrow JATS/XML-to-chunker contract and trivial lexical discrimination. It
  did not exercise the main PDF acquisition/extraction path and is not
  cross-domain retrieval-quality evidence or broad external validation.
- The full performance profile covered discovery, ingestion, PDF/OCR handling,
  chunking, three indexes, four retrieval modes, offline answering and
  recommendation, ASGI requests, frontend build, and eight rendered routes.
  Independent validation accepted all 17 stages, 102 timed samples, 102 RSS
  records, and zero failures.
- The run used WSL2 Linux on an AMD Ryzen 7 5800X with 16 logical CPUs,
  4,012,360 KiB visible RAM, CPU execution, Python 3.12.3, Node 24.14.1, and npm
  11.11.0. It used one probe process at a time and three process-cold plus three
  warm repetitions per stage. OS caches were not flushed, and the interpolated
  p95 over three observations is descriptive rather than a stable tail estimate.
- This bounded local baseline does not establish capacity, saturation,
  concurrency, endurance, asymptotic scaling, or production service levels.
  Evidence: `artifacts/phase6/performance/performance_full_results.json` and
  `artifacts/phase6/performance/performance_validation.json`.

### Prospectively frozen peer-review remediation v2

`data/evaluation/peer_review_remediation_v2_protocol.json` freezes the protocol
before system rankings or answers are consulted. Source-derived case files
freeze Ask development/test IDs, Finder development/test/sensitivity IDs,
positive-only topic labels, exact source locators, technical-corpus selection,
the fixed keyword mode, deterministic providers, answerability threshold,
Finder weights, OCR fixture/configuration, and 5,000-replicate cluster-bootstrap
seed. The public projection is recorded but explicitly not evaluated.

Execution is deliberately separated into three ordered gates:

1. `prepare` validates the exact locked Python environment, clean committed
   evaluation sources, database/source locators, generation-linked technical
   corpus, artifact inventory, splits, and OCR runtime, then writes a freeze
   receipt before retrieval/generation;
2. `evaluate` refuses changed inputs, operates on a temporary SQLite copy,
   rebuilds a temporary keyword index, permits one Ask/Finder/topic/OCR
   evaluation invocation for that fresh freeze/workspace, writes
   structural versionable outputs plus operator-local restricted raw outputs,
   and produces deterministic manuscript macros; and
3. the validator recomputes source identities, case membership, all aggregate
   metrics/intervals/macros, the exact flat-file allowlist, and a completed-
package attestation.

The first accepted source candidate is the confirmatory execution. Later full
runs are deterministic replications of the unchanged protocol and cases, with
no retuning, relabeling, case changes, or result selection. The final report
records that reproduced source-candidate identity separately from the later
evidence commit; any source or protocol change requires a fresh run.

The two fixed-seed shuffled reviews are the same AI-authored procedure applied
twice. Agreement/disagreement describes repeatability only; it is not human
inter-rater reliability or independent validation. Ask labels do not establish
semantic entailment. Finder profiles are synthetic and cannot establish
usefulness, novelty, feasibility, data access, or supervisor fit. Topic labels
are non-exhaustive known positives, so only known-positive recall/coverage and
unadjudicated prediction counts are permitted—not precision, F1, or exact
match. The synthetic scanned fixture exercises the OCR code path but is not a
TTLAB-corpus OCR accuracy study.

The canonical versionable package is
`artifacts/peer_review_remediation/v2/`; extractive answers, source snippets,
generated recommendations, and full topic evidence remain under the ignored
operator-controlled restricted directory and are excluded from release. A
missing or partial package is `not_run`/invalid, never zero or success.

## Engineering verification plan

From the final clean commit, the delivery gate runs:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend audit --audit-level=high
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
make reproduce
make release
make peer-review-v2-validate
make paper
make thesis-assets-frozen
make thesis-compile
```

It additionally runs every evaluation validator, dependency audits, manuscript
source validation, qpdf/pdfinfo/pdffonts/text checks, page rendering, and visual
inspection. `make reproduce` and `make release` are fail-loud delivery gates;
neither a prior performance run nor a partial command proves that the final
clean commit passes them. Exact final commands and outcomes belong in
`docs/peer_review_readiness/FINAL_READINESS_REPORT.md`.

For pre-execution layout checks or a future fresh v2 run, manuscript layout may
be checked only with
`make paper-layout`, `make thesis-layout`, and
`scripts/validate_manuscripts.py --allow-v2-not-run`. Those targets visibly
emit `not run` v2 macros and are not final-readiness builds.

## Legacy scaffold files

`questions.sample.jsonl`, `qa_questions.sample.jsonl`, the older
`extension_eval_cases.jsonl`, `artifact_eval_cases.jsonl`,
`idea_generation_cases_v1.jsonl`, and blank human
review templates remain useful examples/regression scaffolds. They are not the
source of the reported silver/proxy results and must not be cited as gold or
human validation. The authoritative research artifacts are the versioned
`*_silver_v1`, `qa_faithfulness_*`, Phase 2–4, and manifest files identified
above.

## Claim rules

Permitted conclusions characterize this frozen corpus, implemented artefact,
and AI-assisted offline procedure. They do not establish:

- student usefulness or satisfaction;
- supervisor approval or assignment suitability;
- recommendation novelty or real-world feasibility;
- comprehensive researcher expertise or availability;
- production capacity/security/accreditation;
- WCAG or assistive-technology conformance from automated accessibility checks;
- human inter-rater reliability; or
- broad external validity.

Any later human study needs a separate protocol, recruitment/consent and
institutional determination, sample rationale, reviewer training, adjudication,
privacy plan, and newly versioned results.
