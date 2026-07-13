# Evaluation Plan and Execution Status

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

## RQ-to-evaluation map

| RQ | Evaluation | Status | Decision supported |
|---|---|---|---|
| RQ1 corpus/traceability | eligibility/PDF identity audit, section silver review, manifest one-to-one coverage | Executed | 96 papers/719 chunks form the frozen eligible corpus; two mismatches and 36 no-text records remain excluded |
| RQ2 retrieval | keyword, feature-hashing, dense, heuristic/tuned hybrid; dev tuning; test; ablation/sensitivity/statistics | Executed | keyword is the strongest held-out MRR baseline; tuned hybrid superiority is not established |
| RQ3 RAG | atomic claim, citation-link, completeness, answer-point, unsupported knowledge, abstention review | Executed | source support is high but citation correctness, completeness of answers, and abstention need improvement |
| RQ4 advisory/discovery | evidence-only vs full Finder, topic lexical-vs-dense, author audit, full stored-output review | Executed | advisory improvement is not demonstrated; publication evidence and AI-review boundaries must remain visible |
| RQ5 engineering readiness | backend/frontend/security/accessibility tests, performance, reproduction, release scan, PDF preflight | Performance executed; delivery gate pending | validated 17-stage local performance evidence is available, while final clean-commit reproduction/release and document closure remain separate gates |

## Executed datasets

### Section quality

- 40 source-backed AI-reviewed chunks.
- Current output: overall accuracy 0.900; labeled accuracy 0.8889; labeled
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
- Result: keyword held-out MRR 0.9474; dense 0.9386; tuned hybrid 0.8596;
  no family-corrected contrast rejected the null.
- Evidence: `data/evaluation/retrieval_silver_v1.jsonl` and
  `artifacts/phase2/retrieval/`.

### RAG claim/citation review

- 50 cases: 46 answerable, four unanswerable.
- 400 checkable claims, 400 citation links, and 81 answer points.
- Metrics: strict/weighted claim support, citation correctness, citation and
  correct-citation completeness, answer-point coverage, unsupported knowledge,
  answerability/abstention, category results, and errors.
- Result: support 0.995; citation correctness 0.625; strict answer-point
  coverage 0.1358; unanswerable abstention 0/4.
- Optional Ollama comparison was not run because the service was unavailable.
- Evidence: `data/evaluation/qa_faithfulness_*` and
  `artifacts/phase3/qa/`.

### Recommendation proxy comparison

- 28 synthetic profiles; three ranked items per arm; 84 items reviewed in each
  evidence-only/full-Finder arm.
- Two fixed-seed shuffled passes by the same AI procedure.
- Criteria: relevance, source fidelity, fact/future/gap/suggestion separation,
  novelty caution, feasibility, MVP/stretch, risk, skills, evaluation plan, and
  usefulness as an AI proxy.
- Result: full-minus-baseline relevance 0.0238 (95% CI -0.0238 to 0.0714);
  improvement not demonstrated. All feasibility decisions remain partial.
- Twenty-two configurations (the default plus 21 zero/plus/minus-25% one-term
  perturbations) are retained; this is sensitivity analysis, not learned
  tuning.
- Evidence: `data/evaluation/recommendation_profiles_v1.jsonl` and
  `artifacts/phase4/recommendation_proxy_v1/`.

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
- Result: 21 `ai_reviewed`; 27 RAG answers `needs_reprocess`; 48 attributed
  events; hash chain verified; repeat pass zero changes.
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
make paper
make thesis
```

It additionally runs every evaluation validator, dependency audits, manuscript
source validation, qpdf/pdfinfo/pdffonts/text checks, page rendering, and visual
inspection. `make reproduce` and `make release` are fail-loud delivery gates;
neither a prior performance run nor a partial command proves that the final
clean commit passes them. Exact final commands and outcomes belong in
`docs/FINAL_STATUS.md`.

## Legacy scaffold files

`questions.sample.jsonl`, `qa_questions.sample.jsonl`, the older
`extension_eval_cases.jsonl`, `artifact_eval_cases.jsonl`, and blank human
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
