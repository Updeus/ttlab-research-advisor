# Claim-evidence matrix

This matrix covers the major empirical and contribution claims in the abstract,
results, discussion, and conclusion of both manuscripts. It was produced by an
AI-assisted independent audit. Supported means that the named repository
evidence reproduces the narrow claim. It does not mean that an AI-reviewed label
is human ground truth, that a citation is factually entailing, or that the result
generalizes beyond the frozen corpus.

Status vocabulary:

- **supported** — direct code/test/raw-artifact evidence matches the claim;
- **bounded** — evidence matches only with the stated sample, reviewer, revision,
  or construct limitation;
- **stale-revision** — evidence exists, but it is bound to an older commit than
  current HEAD;
- **unsupported** — required executed evidence is absent or contradicts the
  claim;
- **human-required** — only an authorized external actor can establish it.

## Thesis abstract

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| TA-01 | The artifact is a source-traceable research-intelligence platform, not only a chatbot (thesis/chapters/00_abstract.tex:4) | Route/API/model coverage in backend/app/main.py, frontend/src/App.tsx, backend and frontend suites | runtime probe and feature matrix | platform components need no external citation | **supported**, subject to the UI/review defects in the audit |
| TA-02 | Frozen catalogue has 134 records, 98 PDFs, 96 eligible papers, 719 eligible chunks, with two mismatches (00_abstract.tex:6) | inclusion logic in backend/app/ingestion/pdf_parser.py and backend/app/indexing/embedder.py; manifest tests | thesis/generated/evidence_snapshot.json; live DB; corpus snapshot corpus-04a010207327069a | none | **supported** for the frozen snapshot; 36 no-text records remain |
| TA-03 | Keyword, 256-dimensional feature hashing, and pinned 384-dimensional dense indexes cover 719/719 (00_abstract.tex:6) | backend/app/indexing/embedder.py; index-manifest tests | tracked index manifests; fresh rebuild record hash matched tracked dense records | feature-hashing citation supports terminology, not effectiveness | **supported** for ordered eligible records; manifests name old code commit |
| TA-04 | Held-out keyword Recall@3/MRR/nDCG and tuned-hybrid results; no corrected superiority (00_abstract.tex:6) | retrieval_experiment.py; retrieval/statistics tests and validator | Phase 2 raw rankings, summary, paired statistics, tuning manifest | IR metric citations in literature/method | **bounded** to 19 answerable held-out cases plus one unanswerable and same-AI silver judgments |
| TA-05 | QA has high support but poor citation correctness, answer-point coverage, and abstention (00_abstract.tex:8) | QA evaluator and validator tests | qa_faithfulness_metrics_v1.json: support 0.995, correctness 0.625, coverage 0.135802, 0/4 abstention | RAG evaluation citations motivate constructs | **supported negative result**; runtime grounded is only structural |
| TA-06 | Finder has uncertain relevance difference and unresolved feasibility (00_abstract.tex:8) | recommender/proxy evaluator tests | 28 profiles; delta 0.0238; CI [-0.024, 0.071]; 84/84 feasibility partial | recommender literature is contextual | **supported negative/uncertain result**; no student/supervisor benefit evidence |
| TA-07 | Contribution is a reproducible protocol separating traceability, quality, and human validation (00_abstract.tex:10) | reproduction/release scripts and component tests exist; reproduce_all.sh:153-156 suppresses database status updates | component artifacts are hash-bound, but the clean b561fa7 full run recorded 40 status-integrity failures and produced no final manifest | reproducibility practices cited elsewhere | **partly unsupported/contradicted for current HEAD**: protocol exists, but its exact-current full execution fails |

## Thesis results

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| TR-01 | Eligible corpus is internally complete and all authoritative indexes cover 719 chunks (thesis/chapters/10_results.tex:6-17) | manifest validation, stale/partial negative tests | Phase 1 evidence, live manifests, fresh deterministic dense-record comparison | none | **supported** for technical eligibility; not editorial approval |
| TR-02 | Section detector exact accuracy is 0.900; 199 chunks remain Unknown (10_results.tex:14-17) | section-evaluation validator | section silver files and Phase 1 evidence | none | **bounded**: 40 same-AI cases, zero Abstract examples, sparse classes |
| TR-03 | Keyword has highest point estimates; dense equivalence and hybrid superiority were not established (10_results.tex:19-44) | evaluation/statistics code and tests | raw rankings, bootstrap and paired statistics | BM25/SBERT/BEIR citations frame comparison | **supported**; not evidence of universal lexical superiority |
| TR-04 | All tested modes fail the single retrieval unanswerable case (10_results.tex:19-36) | retrieval evaluator | Phase 2 per-query records | none | **supported case observation**, not a population abstention rate |
| TR-05 | QA support 0.995 coexists with correctness 0.625, coverage 0.136, and four false-positive unanswerables (10_results.tex:46-67) | claim/citation evaluation and validation scripts | 400 claim labels, 81 answer points, error taxonomy | RAG evaluation references | **supported negative/mixed result** |
| TR-06 | Finder relevance improvement is uncertain and all feasibility judgments are partial (10_results.tex:68-84) | proxy evaluator and sensitivity code | aggregate and raw profile reviews | recommendation literature | **supported** as same-AI proxy evidence only |
| TR-07 | Lexical topics trade recall for precision; dense prototype is not universally superior (10_results.tex:68-84) | topic evaluator and validator | 60 cases with 24 held out; lexical F1 0.556, dense F1 0.521 | LDA/BERTopic citations are context, not validation | **bounded** by sparse multi-label support and unreviewed production labels |
| TR-08 | Author audit found no excluded leakage/collision/mismatch but 13 possible same-person pairs remain (10_results.tex:84-94) | author audit code/tests | author identity artifact | none | **bounded**: repository audit also records 133 unreviewed identity rows and malformed names |
| TR-09 | Generated-output review appended 48 hash-chained AI events, 21 outputs AI-reviewed and 27 answers need reprocessing (10_results.tex:95-107) | generated-review tests, transition rules | review event table and generated-output manifest | none | **supported** as AI review, not human approval; UI cannot safely execute/display all transitions |
| TR-10 | Performance profile has 17 stages, 102 samples, zero failures on one WSL2 host (10_results.tex:108-110) | performance benchmark/validator tests | performance_full_results.json and validation at commit 5ccf22e...; clean b561fa7 reproduction recorded 40 failures | none | **stale-revision but supported for 5ccf22e only**; it is not current-candidate performance or scale evidence |
| TR-11 | Sanitized release excludes restricted/runtime material and verifies checksums (10_results.tex:110) | release scanner and release tests | old release bundle and validation artifacts | rights boundary documented internally | **stale-revision**: old release passed; current-candidate bundle was absent at baseline |
| TR-12 | Three Europe PMC documents pass fixed lexical top-one checks (10_results.tex:110) | external sanity code/test | three acquisition records and results | Europe PMC license metadata | **supported only as JATS/XML format smoke test**, not PDF or quality validation |

## Thesis discussion and conclusion

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| TD-01 | Traceability remains intact across ingestion, ranking, generation, review, API and UI (thesis/chapters/11_discussion.tex:4-8) | unit/E2E tests and schemas | runtime probe | none | **bounded**: locator fields exist, but public UI can render stale/wrong artifact provenance and runtime grounding is not entailment |
| TD-02 | Source traceability makes failure inspectable but does not establish correct answers (11_discussion.tex:18-23) | verifier implementation demonstrates structural check | QA negative metrics | RAG evaluation citations | **supported and appropriately calibrated** |
| TD-03 | Finder is auditable but not validated advice (11_discussion.tex:24-29) | separate fact/gap/suggestion fields and tests | uncertain delta, all feasibility partial | recommender citations | **supported negative boundary**; UI stale-result defect weakens practical auditability |
| TD-04 | Review governance is attributable and protected (11_discussion.tex:30-34) | auth and hash-chain tests | 48 review events | none | **partly supported**: backend controls exist; role-blind and correction/publication UI breaks the end-to-end workflow |
| TD-05 | Final conclusion says the project was reproducibly evaluated (thesis/chapters/13_conclusion_future_work.tex:4-16) | scripts and component gates exist; current reproducer suppresses vector-status updates | tracked evidence belongs to several older/dirty revisions; clean b561fa7 full reproduction failed with 40 samples and no final manifest | none | **contradicted for current HEAD as an end-to-end completion claim** |
| TD-06 | No human usefulness, novelty, feasibility, expertise, endorsement, WCAG, or production-capacity claim is established (13_conclusion_future_work.tex:8-16; limitations chapter) | UI/accessibility/security tests establish engineering contracts only | same-AI artifacts and one-host benchmark | none | **supported limitation** and must be retained |
| TD-07 | TTLAB authorization is not ethics approval or blanket PDF redistribution permission (thesis/chapters/12_limitations_ethics_validity.tex; availability text) | release exclusions enforce part of boundary | user-provided authorization fact only | human authorization/rights record absent | **bounded/human-required**; wording is appropriately cautious |

## IEEE paper abstract

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| PA-01 | Platform combines keyword, hashing, dense, hybrid, cited QA, Finder, topic/author and review workflows (paper/ieee-paper.tex:48-50) | code/routes and passing suites | runtime probe | related-work references | **supported as implemented capabilities**, not quality |
| PA-02 | Frozen 134/98/96/719 corpus/index facts (paper/ieee-paper.tex:49) | ingestion/index validators | paper generated macros and evidence snapshot | none | **supported** |
| PA-03 | Retrieval test reports keyword and tuned-hybrid results with no Holm-corrected superiority (paper/ieee-paper.tex:49) | statistics implementation/tests | Phase 2 artifacts and paper macros | IR citations | **bounded** to same-AI silver and small held-out set |
| PA-04 | QA reports support, citation correctness and answer coverage (paper/ieee-paper.tex:49) | QA evaluator/validator | Phase 3 artifacts | evaluation citations | **supported**, but paper should state the two partial claims and label-uncertainty boundary |
| PA-05 | Finder relevance difference is uncertain (paper/ieee-paper.tex:49) | proxy evaluator | recommendation aggregate | recommender citations | **supported**, with no human advisory benefit |
| PA-06 | Contribution is a reproducible platform/protocol (paper/ieee-paper.tex:49) | reproduction scripts exist, but exact-current execution has an index-status defect | clean b561fa7 full run failed with 40 samples and no final manifest/checksums | none | **partly unsupported/contradicted for current HEAD** |

## IEEE paper results

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| PR-01 | RQ1 eligible indexes are complete and two mismatches are excluded (paper/ieee-paper.tex:157-176) | manifest validators and negative tests | Phase 1/corpus macros | none | **supported** for frozen technical corpus |
| PR-02 | RQ2 keyword leads, hybrid ablations are negative, no corrected superiority (paper/ieee-paper.tex:178-199) | retrieval experiment/statistics | rankings, sensitivity, ablation and paired files | IR baselines | **supported and appropriately negative** |
| PR-03 | RQ3 claim support is high but citation/coverage/abstention fail (paper/ieee-paper.tex:201-220) | QA evaluator | Phase 3 metrics/errors | RAG evaluation works | **supported negative result**; category presentation needs clarification |
| PR-04 | RQ4 full Finder has uncertain relevance and partial feasibility; topic/identity limits remain (paper/ieee-paper.tex:223-228) | recommendation/topic/identity evaluators | Phase 4 artifacts | recommender/topic references | **supported only as same-AI proxy evidence** |
| PR-05 | Generated review is AI-only and historical answers need reprocessing (paper/ieee-paper.tex:228) | review logic/tests | 48 events/21 AI-reviewed/27 needs-reprocess | none | **supported**, not human approval |
| PR-06 | Evaluation Dashboard figure shows current executed state (paper/ieee-paper.tex:230-238) | dashboard endpoint/tests | files exist | none | **not established as current**: dashboard uses file existence/mtime and evidence revisions predate HEAD |
| PR-07 | RQ5 performance summary is complete (paper/ieee-paper.tex:240-254) | performance validator | old 5ccf22e artifact; clean b561fa7 run reached all 17 stage names but recorded 40 failures | none | **stale-revision but supported for measured 5ccf22e host/commit only** |

## IEEE paper discussion and conclusion

| ID | Major claim and source anchor | Code/test evidence | Experiment/database/generated evidence | Citation or external evidence | Assessment |
|---|---|---|---|---|---|
| PD-01 | Engineering contribution is evidence boundary, not a new retrieval algorithm (paper/ieee-paper.tex:245-246) | architecture/contracts | all phase artifacts | related-work positioning | **supported and appropriately scoped** |
| PD-02 | Hybrid label and feature hashing must not be treated as quality/semantic claims (paper/ieee-paper.tex:248) | retriever/provider implementation | negative hybrid results | feature-hashing/IR citations | **supported**, but API still exposes a semantic alias for feature hashing |
| PD-03 | Traceability does not repair answer quality (paper/ieee-paper.tex:250) | structural verifier | QA negative metrics | RAG evaluation citations | **supported** |
| PD-04 | Finder is recommendation prototype, not validated advisor (paper/ieee-paper.tex:252,270) | heuristic recommender and verifier | uncertain proxy result | recommender literature | **supported limitation** |
| PD-05 | Clean-commit full reproduction and sanitized release verifiers passed (paper/ieee-paper.tex:254) | scripts and older release verification; current reproduce_all.sh:153-156 causes status divergence | clean b561fa7 run failed at performance-full with 40 failures; no current manifest/checksums/release followed | none | **contradicted for current candidate**; repair, rerun, and retain or reduce the claim |
| PD-06 | Automated accessibility checks passed but WCAG/assistive usability are not established (paper/ieee-paper.tex:254) | frontend axe/E2E suite | route capture report | none | **supported**, but complex Finder/Evaluation/authenticated states lack axe coverage |
| PD-07 | TTLAB authorization, no participants, no ethics-approval claim, no blanket redistribution (paper/ieee-paper.tex:265) | release exclusions | authorization is an author-provided fact | formal record external | **appropriately bounded; human-required for submission attestation** |
| PD-08 | Sanitized release contains code/permitted metadata/configs/manifests/checksums (paper/ieee-paper.tex:267-270) | release implementation/tests | older bundle only at baseline | rights decisions external | **stale-revision** and conditional on the actual rights matrix |

## Unsupported or externally undecidable claims that must not be introduced

The repository does not support any of the following:

- human, student, supervisor, author, or industry usefulness;
- thesis/project novelty, practical feasibility, completion probability, or
  supervisor fit;
- factual correctness merely because a source locator is present;
- human approval from ai_reviewed state;
- WCAG or PDF/UA conformance;
- production capacity, security certification, or deployment approval;
- research-ethics approval or exemption;
- blanket third-party PDF/text redistribution rights;
- exact-current reproducibility until the final candidate manifest/checksums and
  release are retained and independently verified.

Existing manuscript limitations that state these negatives are evidence-bearing
and must not be removed to make the documents appear stronger.
