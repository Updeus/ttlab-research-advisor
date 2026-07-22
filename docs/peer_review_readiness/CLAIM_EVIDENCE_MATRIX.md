# Claim-evidence matrix

This matrix maps the major empirical and contribution claims in the current
thesis and IEEE paper to repository evidence. It is an AI-assisted evidence
audit, not human peer review. A source locator establishes traceability; it does
not by itself establish factual correctness or entailment. Likewise, an
AI-silver judgment is not a human gold label.

Status vocabulary:

- **supported** — direct code, test, database, or artifact evidence establishes
  the narrow claim;
- **bounded** — the claim is supported only within the stated corpus, sample,
  protocol, revision, or construct boundary;
- **historical** — valid retained evidence from an explicitly identified older
  revision, not a measurement of the delivery revision;
- **unsupported** — the required evidence is absent or contradicts the claim;
- **human-required** — only an authorized external actor can establish it.

## Provenance layers used by both manuscripts

| Layer | Exact identity | Permitted use |
|---|---|---|
| Audit-baseline evidence | Commit `b561fa73c1de50569d7e76261b2aa37195524c21`; frozen corpus `corpus-04a010207327069a` | Original audit findings and old Phase 1--4 values remain retained for audit traceability. They are not the v1-form measurements consumed by the final manuscripts. |
| Post-remediation v1-form evidence | Frozen corpus `corpus-f4638c633bea82b0`; Phase 1--4 artifacts; historical performance source commit `73092e48f173b74f726659bd5b98224545ac23bb` | Retrieval, QA, Finder, topic/author, review, performance, and external-sanity values used by the final manuscripts. These are historical relative to delivery HEAD, not delivery-HEAD measurements. |
| Prospective v2 evaluation | Source commit `0d4b9bdcb657034beab5c288ab174983eb0760e3`; `artifacts/peer_review_remediation/v2/manifest_v2.json` SHA-256 `bdc8e8b289d36834479f7bcc1c2efc9857b9812171dd3d4df7f2bff6680e18d9`; validation attestation SHA-256 `f6d320bc246666bd19e7c6642c49e40b53d3acb3b52a789599e1eb3a290f34b7` | Prospective AI-silver QA, Finder, positive-only topic, and synthetic OCR-fixture results. The package has 17 versionable files; its manifest records three rights-sensitive full-raw files retained outside version control. It did not exercise the public projection. |
| Delivery source and manuscripts | Current `codex/peer-review-remediation` branch, later than `0d4b9bd`; final exact delivery commit and backend test count belong in `FINAL_READINESS_REPORT.md` | Implementation fixes, generated macros, final PDFs, and verification. Later delivery edits must not be presented as if prospectively re-evaluated at `0d4b9bd`. |
| Governance screenshots | Historical capture at clean source commit `9a274b82d0f7fa68952369d5ec68565b0a93cbb1`; current deterministic fixtures and hashes in `thesis/figures/screenshots/governance-capture-manifest.json` at source commit `e4618a613e7537b43d3659581137e3234fcc6cb5` | Historical implementation evidence retains the empty public projection. Current synthetic-response fixtures show the Idea Generator and authenticated Admin Control contracts. Neither set is evaluation, human-review, approval, or user-study evidence. |

## Thesis abstract

| ID | Major claim and manuscript anchor | Code/test path | Experiment, database, or generated evidence | Citation/external evidence | Assessment |
|---|---|---|---|---|---|
| TA-01 | The artifact is a source-traceable research-intelligence platform, not only a chatbot (`thesis/chapters/00_abstract.tex`) | `backend/app/main.py`, API routes, `frontend/src/App.tsx`, backend/frontend suites | Route/build/E2E evidence; evidence contracts in `thesis/generated/` | Related work establishes context, not implementation | **supported** as implemented scope; no quality or benefit follows from route coverage |
| TA-02 | Frozen technical corpus has 134 catalogue records, 96 eligible full-text papers, 719 eligible chunks, and two excluded PDF/title mismatches | `backend/app/ingestion/pdf_parser.py`, `backend/app/indexing/embedder.py`, corpus/index invariant tests | `artifacts/phase1/phase1_evidence.json`; `thesis/generated/evidence_snapshot.json`; generated macros | None required | **supported** for the frozen technical snapshot; 98 local PDFs imply 36 records without eligible text, and 199 eligible chunks retain `Unknown` section |
| TA-03 | Keyword, feature-hashing, and pinned learned-dense indexes cover the complete eligible technical set | Index builders, manifest validation, stale/partial/configuration mismatch tests | Phase 1 manifests and `thesis/generated/evidence_macros.tex` | Feature-hashing and dense-model citations support terminology only | **supported**; feature hashing is a lexical signed-hashing baseline, not learned semantic retrieval |
| TA-04 | The independent public projection is empty and fails closed | Public-selection predicate and public API tests; Finder diagnostics | Governance capture manifest records zero searchable papers/chunks; v2 manifest says `public_projection_exercised: false` | Human approval/rights decisions are external | **bounded**: the empty state is observed at screenshot commit `9a274b8`; v2 is technical-corpus evidence, not public behavior |
| TA-05 | Historical QA had strict answer-point coverage 11/81 (0.135802), citation correctness 0.652695, and unanswerable abstention 1/4 | `backend/app/evaluation/qa_faithfulness_eval.py` and validator tests | `artifacts/phase3/qa/qa_faithfulness_metrics_v1.json`; historical manuscript macros | RAG evaluation citations motivate constructs | **historical supported negative result**; structural citation presence is not correctness or entailment |
| TA-06 | Prospective held-out QA has answer-point coverage 3/16 (0.1875), exact-locator precision 1/11 (0.090909), citation completeness 0.846154, false-positive rate 1.0, and zero abstention | Frozen v2 runner/validator and package-recovery tests | `qa_metrics_v2.json`, `manifest_v2.json`, and `validation_attestation_v2.json` | None required | **bounded negative/mixed result** on 12 distinct held-out AI-silver cases; 0.1875 is numerically above 0.135802 but is not a paired improvement estimate |
| TA-07 | Finder Hit@3 worsens relative to evidence-only ranking; topics are positive-only; OCR is a fixture result | Frozen v2 runner/validator | `finder_metrics_v2.json`, `topic_metrics_v2.json`, `ocr_fixture_results_v2.json` | Recommendation/topic/OCR citations provide context only | **bounded**: Finder test Hit@3 is 1.0 versus 0.8 (delta -0.2); topic recall is 0.75 on known positives; OCR CER/WER 0 applies only to one synthetic raster fixture |
| TA-08 | Contribution is an evidence-calibrated platform and reproducible evaluation package, not a validated advisor | Reproduction, release, manifest, and validation code/tests | Validated v2 manifest/attestation plus final verification evidence | Reproducibility literature provides framing | **supported with revision boundary**; human usefulness, novelty, feasibility, public effectiveness, and supervisor fit remain unsupported |
| TA-09 | The current public Idea Generator returns schema-validated, source-aware directions while separating paper-informed output from general suggestions | `backend/app/intelligence/idea_generator.py`, `backend/app/api/recommendations.py`, `frontend/src/pages/ExtensionFinder.tsx`; backend/frontend Idea Generator tests | Four formative cases in `data/evaluation/idea_generation_cases_v1.jsonl`; current deterministic interface fixture | None required for the narrow software-contract claim | **supported as post-evaluation engineering behavior**; no live-model quality, novelty, feasibility, usefulness, or human-validation claim is supported |

## Thesis results

| ID | Major claim and manuscript anchor | Code/test path | Experiment, database, or generated evidence | Citation/external evidence | Assessment |
|---|---|---|---|---|---|
| TR-01 | RQ1: 134 records, 98 PDFs, 96 eligible papers, 735 raw/719 eligible chunks, two mismatches, and 199 `Unknown` eligible sections (`thesis/chapters/10_results.tex`) | Ingestion, generation reconciliation, index validation, and negative tests | Phase 1 evidence, SQLite snapshot, generated macros | None | **supported** for technical eligibility; technical eligibility is not editorial/public approval |
| TR-02 | Section silver review reports 0.900 exact accuracy | Section evaluator and validator | `artifacts/phase1/section_quality_metrics.json` | None | **bounded** to 40 AI-silver cases with sparse/zero support for some labels; 199 unknown sections remain |
| TR-03 | RQ2: historical keyword has the highest held-out point estimates and no corrected comparison establishes tuned-hybrid superiority | Retrieval evaluator/statistics and tests | Phase 2 raw rankings, summary, tuning, ablations, paired statistics, generated rows | IR citations define metrics/baselines | **historical supported** on 19 answerable test questions plus one unanswerable; not universal lexical superiority |
| TR-04 | Every historical retrieval mode answers the single unanswerable test query | Retrieval evaluator | Phase 2 per-query rankings/error taxonomy | None | **historical case observation**; one case is not a stable population rate |
| TR-05 | RQ3: high local support coexists with weak historical citation choice, 11/81 coverage, and 1/4 unanswerable abstention | QA evaluator and validator | Phase 3 raw reviews/metrics | RAG evaluation citations | **historical supported negative/mixed result**; exact rates are 0.991018 strict support, 0.652695 citation correctness, 0.135802 coverage, and 0.25 unanswerable abstention |
| TR-06 | RQ4: historical Finder did not demonstrate relevance improvement, usefulness, or feasibility | Recommendation proxy evaluator, schema/contract tests | Phase 4 v1 aggregate/raw/review/sensitivity artifacts | Recommendation literature | **historical bounded negative result** based on synthetic profiles and same-AI proxy review, not student or supervisor validation |
| TR-07 | RQ5: historical topic methods show a precision/recall trade-off; identities remain unresolved; generated review is AI-only and append-only | Topic/author and generated-review code/tests | Phase 4 topic/author and generated-output-review artifacts | Topic citations contextual only | **historical bounded**; topic silver labels and author links are not approval, expertise, endorsement, or availability |
| TR-08 | Prospective QA reports 0.1875 held-out strict point coverage, 0.090909 exact locator precision, 0.846154 citation completeness, 1.0 false-positive rate, and 0 abstention | Frozen v2 runner and independent validator | v2 QA outputs, shuffled passes, metrics, manifest, attestation | None | **bounded negative/mixed result**; the second pass is repeated same-AI inspection, not inter-rater agreement; locator precision is not entailment |
| TR-09 | Prospective Finder is worse than evidence-only on held-out Hit@3 and does not establish usefulness or feasibility | Frozen paired Finder protocol | Test Hit@3 1.0 evidence-only versus 0.8 full, delta -0.2 (95% cluster CI [-0.6, 0]); MRR 0.666667 versus 0.6, delta -0.066667 | None | **bounded negative result** over five held-out synthetic profiles; template/constraint fidelity is a contract check only |
| TR-10 | Prospective topics report known-positive recall, not precision/F1; OCR exercises only a synthetic raster path | Frozen v2 topic/OCR protocol | Topic test recall 9/12 = 0.75, case coverage 0.625, 9/18 predictions unadjudicated; OCR CER/WER 0 with exact repeated output | None | **bounded**: positive-only labels cannot classify unadjudicated predictions as false positives; fixture performance is not corpus OCR accuracy |
| TR-11 | Historical performance completed 17 stages and 102 samples with zero recorded failures on one WSL2 host | Performance benchmark/validator tests | `artifacts/phase6/performance/performance_full_results.json`, source commit `73092e48...`, provenance SHA-256 `2a71252d...` | None | **historical supported engineering evidence**; CPU-only, concurrency-one, no scale/capacity/SLO claim |
| TR-12 | Three licensed Europe PMC JATS/XML records pass fixed lexical top-one checks | External-sanity code/tests | Phase 6 external-sanity records/results | Europe PMC license metadata | **bounded smoke test** for JATS/XML/chunker compatibility, not PDF ingestion or cross-domain quality |
| TR-13 | Post-evaluation Idea Generator and Admin Control additions satisfy typed request, source-alias, provider-identity, authorization, and preview-staleness contracts | Idea Generator, admin-auth/control, bulk/publication preview tests; frontend Idea Generator and Admin Control tests | Four formative Idea Generator cases and deterministic synthetic interface fixtures | None | **supported engineering verification only**; the additions do not modify or improve any frozen v1/v2 effectiveness estimate |

## Thesis discussion and conclusion

| ID | Major claim and manuscript anchor | Code/test path | Experiment, database, or generated evidence | Citation/external evidence | Assessment |
|---|---|---|---|---|---|
| TD-01 | Traceability makes failures inspectable but does not establish correctness (`thesis/chapters/11_discussion.tex`) | Evidence schemas, citation verifier, API/UI evidence components | Historical and v2 QA negative results | RAG evaluation literature | **supported and appropriately calibrated** |
| TD-02 | Finder separates paper facts, paper-stated future work, inferred gaps, and generated suggestions | `backend/app/intelligence/extension_recommender.py`, API/UI/schema tests | Finder raw outputs and contract checks | Recommendation literature | **supported as a data contract**; novelty, feasibility, completion probability, and supervisor fit remain unsupported |
| TD-03 | Review events are attributed/append-only, and AI review cannot create human approval | Admin/review transition, auth, idempotence, and event-chain tests | Generated-output review artifacts/database state | None | **supported engineering boundary**; no human review is claimed |
| TD-04 | Reproduction is revision- and rights-bounded | V2 runner/validator/finalizer, release and reproduction code/tests | 17-file versionable v2 package; three restricted raw files named/hashed but not committed; final delivery evidence in `FINAL_READINESS_REPORT.md` | Rights status is external | **supported with explicit boundary**; exact full-corpus reruns require lawful local corpus/model access |
| TD-05 | No human usefulness, novelty, feasibility, expertise, endorsement, WCAG/PDF-UA, or production-capacity claim is established | Engineering tests establish only contracts | Same-AI artifacts; single-host benchmark; `pdfinfo` reports both PDFs untagged | Human/venue/deployment decisions external | **supported limitation** and must be retained |
| TD-06 | TTLAB authorization is project/corpus-use authorization, not ethics approval or blanket redistribution permission | Release exclusions implement part of the boundary | User-supplied authorization fact only | Formal approvals/rights determinations absent | **bounded/human-required**; current wording is conservative |
| TD-07 | The thesis reaches the substantive minimum and cites its generated evidence | Manuscript validator and LaTeX build | `build/thesis.pdf`: 97 A4 pages; `build/thesis.bbl`: 38 entries | None | **supported engineering fact**, not evidence of academic quality by page count |

## IEEE paper abstract and contributions

| ID | Major claim and manuscript anchor | Code/test path | Experiment, database, or generated evidence | Citation/external evidence | Assessment |
|---|---|---|---|---|---|
| PA-01 | Platform combines full-text discovery, cited QA, an evaluated structured Finder, a current conversational Idea Generator, topic/author exploration, and protected review (`paper/ieee-paper.tex`, Abstract/Introduction) | Backend routes/models and frontend routes/components/tests | Runtime/build/E2E evidence; formative Idea Generator cases | Related work positions contribution | **supported as implemented capability**, not effectiveness; Idea Generator is post-evaluation |
| PA-02 | Historical corpus/index and retrieval facts are complete for the technical snapshot | Ingestion/index/retrieval validators | Phase 1--2 artifacts and `paper/generated/metrics.tex` | IR citations | **historical bounded** to the frozen technical corpus and AI-silver queries |
| PA-03 | Historical QA and Finder negatives remain visible | QA/Finder evaluators | Phase 3--4 artifacts and generated macros | Evaluation/recommendation citations | **historical supported negative evidence**; 0.135802 coverage, 0.652695 citation correctness, 1/4 abstention, and no Finder benefit must not be hidden |
| PA-04 | Prospective v2 reports exact-locator QA, paired Finder, positive-only topics, and OCR fixture outcomes | Frozen v2 runner/validator | Validated v2 package at source `0d4b9bd...` | None | **bounded AI-silver evidence**; it did not exercise the empty public projection |
| PA-05 | Paper contribution is the evidence boundary rather than a new retrieval algorithm or validated advisor | Architecture/contracts/tests | Historical negatives and prospective package | Related-work citations | **supported and appropriately scoped** |

## IEEE paper results, discussion, and conclusion

| ID | Major claim and manuscript anchor | Code/test path | Experiment, database, or generated evidence | Citation/external evidence | Assessment |
|---|---|---|---|---|---|
| PR-01 | RQ1: all three historical indexes cover 719/719 eligible chunks, with mismatch/no-text/unknown-section limitations | Manifest validation and negative tests | Phase 1 evidence/macros | None | **historical supported**; not public approval |
| PR-02 | RQ1: keyword has highest historical point estimates; tuned hybrid superiority is not established | Retrieval/statistics code/tests | Phase 2 rankings, intervals, paired tests, ablations | IR metric/baseline citations | **historical supported**, including the adverse unanswerable case |
| PR-03 | RQ2: historical strict QA coverage is 11/81 and prospective coverage is 3/16 | Historical/v2 evaluators and validators | Phase 3 metrics and v2 QA metrics | RAG evaluation citations | **bounded**; the 0.1875 prospective estimate is only a descriptive non-paired numerical difference from 0.135802 |
| PR-04 | RQ2: prospective exact-locator precision is 0.090909, completeness 0.846154, false-positive rate 1.0, and abstention 0 | Frozen v2 validator | `qa_metrics_v2.json` and attestation | None | **bounded negative/mixed result**; no factual-correctness or entailment claim |
| PR-05 | RQ2: full Finder underperforms evidence-only ranking on held-out Hit@3 | Finder protocol/validator | `finder_metrics_v2.json`: delta -0.2, CI [-0.6, 0] | None | **bounded negative result**; no student/supervisor benefit evidence |
| PR-06 | RQ2: topic recall is positive-only and OCR error is fixture-only | Topic/OCR protocol/validator | `topic_metrics_v2.json`, `ocr_fixture_results_v2.json` | None | **bounded**; precision/F1 and corpus OCR claims are unsupported |
| PR-07 | RQ3: historical performance is a single-host engineering profile, not capacity evidence | Performance benchmark/validator | 17 stages, 102/102 samples, source `73092e48...` | None | **historical supported**; it is not a delivery-commit benchmark |
| PR-08 | Public routes fail closed and v2 does not validate public behavior | Public API/tests and selection predicate | Governance capture at `9a274b8`; v2 manifest `public_projection_exercised: false` | Human approval/rights are external | **bounded** with explicit screenshot revision; current public content remains empty pending external decisions |
| PR-09 | The sanitized/versionable package excludes rights-sensitive full raw text | Release/reproduction/frozen validation code/tests | 17 versionable files; three restricted files recorded and excluded; manifest/attestation hashes above | Rights decisions external | **supported technical packaging boundary**, not a blanket rights determination |
| PR-10 | Automated frontend checks/builds pass, but no WCAG or assistive-usability claim follows | Frontend unit/integration/accessibility/E2E tests | 67 frontend tests, successful build, 9 E2E scenarios | Accessibility standards contextual only | **supported engineering evidence**; complex human accessibility remains unevaluated |
| PR-11 | Final manuscript fits the required paper envelope | Manuscript validator and LaTeX build | `build/ieee-paper.pdf`: 6 Letter pages; `build/ieee-paper.bbl`: 21 cited entries | Venue acceptance remains external | **supported format fact**; no venue acceptance claim |
| PR-12 | Ethics, authorization, AI-use, availability, and negative-result boundaries are retained | Source/document validation | Paper source/PDF and release exclusions | Formal approvals/rights absent | **appropriately bounded**; Codex/LLM work is AI assistance, not human assessment |

## Unsupported or externally undecidable claims that must not be introduced

The repository does not establish any of the following:

- human, student, supervisor, author, public, or industry usefulness;
- thesis/project novelty, practical feasibility, completion probability,
  supervisor availability, or supervisor fit;
- factual correctness or entailment merely because a source locator is present;
- human approval from an `ai_reviewed` state or repeated same-AI inspection;
- superiority of the prospective QA result over historical 0.135802 coverage;
- topic precision/F1 from positive-only labels, or corpus OCR accuracy from the
  synthetic fixture;
- public-search effectiveness from technical-corpus evaluation;
- WCAG or PDF/UA conformance (both final PDFs are untagged);
- production capacity, security certification, deployment approval, or venue
  acceptance;
- university research-ethics approval or exemption;
- blanket third-party PDF, extracted-text, or full-raw-output redistribution
  rights.

Existing negative and null findings are evidence-bearing results and must not be
removed or softened merely to make the manuscripts appear stronger.
