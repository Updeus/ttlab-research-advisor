# Evaluation Protocol and Evidence Registry

## Purpose

This protocol separates four kinds of evidence:

1. corpus/index integrity;
2. offline quality evaluation against AI-reviewed silver judgments;
3. engineering verification through tests, builds, security checks, and
   preflight; and
4. external-only evidence such as human usability, supervisor approval,
   institutional authorization, and venue validation.

Only the first three can be produced from the repository. A green test suite or
a structurally cited answer is never substituted for a quality judgment.

## Historical v1 execution registry

The rows below are retained descriptive v1 evidence. They are not upgraded or
relabeled as prospective evidence after remediation.

| Evaluation | Status at this snapshot | Cases/units | Primary evidence |
|---|---|---:|---|
| Corpus/index integrity | Executed | 134 records; 719 eligible chunks | `artifacts/phase1/phase1_evidence.json` |
| Section labeling | Executed, AI silver | 40 chunks | `data/evaluation/section_quality_silver_v1.jsonl` |
| Retrieval baselines/tuning/ablations | Executed, AI silver | 50 queries (30 dev/20 test) | `artifacts/phase2/retrieval/` |
| RAG claim/citation review | Executed, AI-assisted formative | 50 QA cases | `artifacts/phase3/qa/` |
| Recommendation comparison | Executed, AI-assisted proxy | 28 profiles; 84 items/arm | `artifacts/phase4/recommendation_proxy_v1/` |
| Topic classification and author audit | Executed, AI silver | 60 papers; 39 labels | `artifacts/phase4/topic_author/` |
| Persisted generated-output review | Executed, AI review | 48 outputs | `artifacts/phase4/generated_output_review/` |
| External format sanity | Executed | 3 CC BY documents/queries | `artifacts/phase6/external_sanity/` |
| Full performance profile | Executed and independently validated | 17 stages; 102 timed/RSS samples | `artifacts/phase6/performance/` |
| Human usability/advisory validation | Not conducted | No participants | external/future study only |
| Peer-review remediation v2 | Prospectively specified; completion is established only by the canonical package manifest and attestation | 18 Ask cases; 10 Finder profiles; 12 topic cases; one deterministic OCR fixture | `data/evaluation/peer_review_remediation_v2_protocol.json`; when run, `artifacts/peer_review_remediation/v2/` |

## Historical v1 corpus and common controls

All corpus-dependent quality experiments use snapshot
`corpus-04a010207327069a`, hash
`04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5`,
with 96 eligible papers and 719 eligible chunks. Sixteen chunks from two
metadata/PDF mismatches are excluded, and 36 catalogue-only/no-text records
remain out of the experimental corpus. The keyword, 256-dimensional feature-
hashing, and 384-dimensional dense representations use this same eligibility
boundary. Vector manifests must match ordered chunk IDs and source hashes.

Every experiment retains its input hash, code/configuration identity, fixed
seeds, raw per-case output, aggregate result, and limitations. A manifest or
validator failure invalidates the associated aggregate; a missing result is
`not_run`, not zero.

The v2 run does not silently inherit this historical identity. Its `prepare`
gate recomputes and freezes the current generation-linked technical corpus,
effective retrieval-source hashes (including retrieval-affecting metadata),
source PDF/extraction/chunk artifact inventory, exact code/lock identities, and
the public-selection predicate that is recorded but not exercised.

## AI-reviewed silver procedure

Silver labels are prepared from source paper metadata and page/chunk evidence,
not from system rankings. Each case records paper IDs, chunk/page/section
locators, a paraphrased rationale, answerability or review outcome, reviewer
identity/type, timestamp, and pass. The same AI reviewer first creates labels
and later verifies them in a fixed-seed shuffled order. Verification decisions
are the adjudicated labels; disagreements remain in the artifacts.

Consistency statistics quantify repeatability of one AI-assisted procedure.
They must not be described as human inter-rater reliability or independent
review. The retrieval set recorded exact case agreement 0.88 and a Cohen-style
binary candidate-judgment kappa 0.7059 over 70 candidate judgments. The topic
set recorded exact case agreement 0.8333 (50/60). QA review recorded claim-label
exact agreement 1.0 and answer-point exact agreement 0.963. These figures do not
measure correctness against a human reference.

The v2 shuffled passes retain the same boundary: they are repeated applications
of one AI-authored deterministic review procedure, not two independent raters.
The v2 validator may establish structural repeatability and exact recomputation
of recorded decisions; it cannot convert them into human validation or semantic
entailment.

## Retrieval evaluation

### Cases and split

`data/evaluation/retrieval_silver_v1.jsonl` contains 50 cases: 30 development
and 20 held-out test. Categories cover exact factual lookup, methods, results,
limitations/future work, title/author/venue, topic/application, comparison,
broad intent, multi-paper synthesis, hard negatives, and out-of-corpus cases.
There are 44 low-uncertainty and six medium-uncertainty labels. All four
out-of-corpus cases were separately checked with expanded direct title and
chunk-text searches.

Development cases select hybrid weights and support sensitivity analysis. Test
labels are used only once for final comparison. Each mode uses the same frozen
candidate pools (150 chunks per component), retrieval depth 50, unique-paper
cutoff 10, filters, and unjudged-as-nonrelevant policy.

### Metric definitions

For answerable query `q`, let `Gq` be the judged relevant paper set and `Rq,k`
the first `k` unique retrieved papers.

- `set Recall@k = |Gq intersection Rq,k| / |Gq|`.
- `Hit@k = 1` when the intersection is non-empty, otherwise `0`.
- `Precision@k = |Gq intersection Rq,k| / k`.
- `MRR` is the mean reciprocal rank of the first relevant paper; a miss is zero.
- `DCG@10 = sum((2^rel_i - 1) / log2(i + 1))` for ranks 1–10, and
  `nDCG@10 = DCG@10 / IDCG@10`; graded relevance is retained when available.
- Unanswerable false-positive rate is the fraction of out-of-corpus queries for
  which a mode returns at least one result under the evaluated policy.
- Unanswerable abstention rate is the corresponding fraction with no returned
  result/explicit abstention.

Set recall and hit rate are reported separately. Unanswerable cases are not
given an artificial relevant set and are omitted from relevance-metric means.

### Modes and tuning

- **Keyword:** SQLite FTS/fallback lexical retrieval with baseline controls.
- **Feature hashing:** deterministic signed token hashing, 256 dimensions; not
  a learned semantic encoder.
- **Dense:** pinned `all-MiniLM-L6-v2`, 384 dimensions, revision
  `826711e54e001c83835913827a843d8dd0a1def9`.
- **Heuristic hybrid:** the pre-experiment runtime combination.
- **Tuned hybrid:** development-selected keyword 0.10/dense 0.80 with query
  expansion, metadata, section, evidence, topic, and diversity terms enabled.

The search grid and development objective are stored in
`artifacts/phase2/retrieval/tuning.json`. Sensitivity evaluates keyword/dense
neighbors 0.05/0.85, 0.15/0.75, 0.20/0.70, and 0.30/0.60 on development cases
only. Individual and cumulative ablations retain per-query rankings.

### Statistical analysis

Each reported aggregate has a fixed-seed 10,000-repetition query bootstrap 95%
percentile interval. Tuned-minus-baseline test-set contrasts use two-sided
paired randomization on answerable query-level differences. Holm-Bonferroni
corrects all available tuned-vs-baseline metric comparisons as one experiment
family at alpha 0.05. The unit is the query; the procedure does not model silver
label or corpus-selection uncertainty.

### Held-out results and interpretation

| Mode | Set Recall@3 (95% CI) | Set Recall@10 | MRR (95% CI) | nDCG@10 (95% CI) |
|---|---:|---:|---:|---:|
| Keyword | 0.9395 [0.8658, 1.0000] | 1.0000 | 0.9474 [0.8684, 1.0000] | 0.9580 [0.8998, 0.9981] |
| Feature hashing | 0.6535 [0.4430, 0.8509] | 0.7035 | 0.5877 [0.4121, 0.7632] | 0.5823 [0.4114, 0.7449] |
| Dense | 0.9158 [0.8211, 1.0000] | 0.9895 | 0.9386 [0.8421, 1.0000] | 0.9390 [0.8703, 0.9941] |
| Heuristic hybrid | 0.7947 [0.6105, 0.9474] | 0.9167 | 0.8132 [0.6500, 0.9474] | 0.8293 [0.6908, 0.9394] |
| Tuned hybrid | 0.8561 [0.7070, 0.9737] | 0.9254 | 0.8596 [0.7193, 0.9737] | 0.8713 [0.7443, 0.9674] |

The tuned hybrid did not demonstrate superiority. Its MRR difference versus
keyword was -0.0877 (paired bootstrap 95% CI -0.2368 to 0.0439) and versus
dense was -0.0789 (-0.1754 to 0). It exceeded feature hashing by 0.2719
(0.0263 to 0.5175), but the paired randomization p-value was 0.0605 and the
family-adjusted p-value was 1.0. None of 28 family-corrected contrasts rejected
the null. Every mode returned a result for the one held-out unanswerable query,
so held-out false-positive rate was 1.0 and abstention rate 0.0.

The deterministic held-out taxonomy marks one extraction signal, two intent-
mismatch signals, and one corpus-absence case. It is diagnostic, not a causal
attribution. All failures remain in the raw artifacts.

## RAG claim and citation evaluation

The 50-case QA set includes 46 answerable and four unanswerable cases. The
offline extractive heuristic-hybrid answerer produced 400 checkable claims and
81 answer points. The AI review assigns `supported`, `partial`, or
`unsupported` to each claim; citation links are `correct`, `partial`, or
`incorrect`; answer points are `covered`, `partial`, or `omitted`.

Strict metrics give no credit for partial labels. Weighted supplements award
0.5 to partial labels and are clearly named. Citation completeness asks whether
each checkable claim has a citation; correct-citation completeness additionally
requires a correct link. Abstention accuracy is computed over all answerability
decisions, while unanswerable abstention rate isolates the four unanswerable
cases. Fixed-seed 10,000-repetition confidence intervals resample QA cases as
clusters.

Headline results are:

| Metric | Estimate | 95% CI |
|---|---:|---:|
| Strict supported-claim rate | 0.9950 | [0.9872, 1.0000] |
| Citation precision/correctness | 0.6250 | [0.5641, 0.6913] |
| Citation completeness | 1.0000 | [1.0000, 1.0000] |
| Correct-citation completeness | 0.6250 | [0.5641, 0.6913] |
| Strict answer-point coverage | 0.1358 | [0.0674, 0.2111] |
| Unsupported-claim rate | 0.0000 | [0.0000, 0.0000] |
| Abstention accuracy | 0.9200 | [0.8400, 0.9800] |
| Unanswerable abstention rate | 0.0000 | [0.0000, 0.0000] |

The apparent combination of high claim support and low answer-point coverage is
not contradictory: extractive sentences can be supported while answering the
wrong or incomplete part of the question. Forty-four cases were incomplete, 42
had off-topic retrieval, 14 missed within-paper evidence, and all four
unanswerable cases failed to abstain. Therefore runtime `grounded` must not be
interpreted as answer correctness or completeness.

The Ollama CLI was present but its service was unavailable. The artifact
explicitly records `not_run_service_unavailable`; no model comparison is
reported.

## Recommendation proxy evaluation

Twenty-eight synthetic profiles produce three ranked items per arm (84 each).
The evidence-only baseline returns papers and passages. The full Finder adds
structured fact/gap/suggestion separation, MVP/stretch scope, risk, skills,
data, and evaluation-plan fields. The evaluator calls the explicitly authorized
technical scope with `persist=False`, leaving live recommendation rows
unchanged. This is an offline experiment boundary, not evidence about public
request behavior or the independently governed public projection.

The evidence-only paper-relevance score was 0.6310 (95% CI 0.5238–0.7262); the
full Finder score was 0.6548 (0.5595–0.7500). The paired difference was 0.0238
(-0.0238 to 0.0714), so improvement is not demonstrated. All 84 full-Finder
items passed source fidelity, fact/future-work/gap/suggestion separation,
novelty caution, MVP, stretch-goal, risk, and skills checks. All 84 feasibility
judgments were partial because source evidence cannot establish a student's
actual capacity or data access. Evaluation plans had 72 passes and 12 partials.
These are AI-proxy rubric judgments, not student ratings.

The weights (0.30 retrieval, 0.20 interest, 0.15 skills, 0.10 each data/time/
difficulty, 0.05 evidence) are hand-authored. Twenty-two configurations (the
default plus 21 zero/plus/minus-25% one-term perturbations) are retained in
`weight_sensitivity.json`; zeroing interest match was the most
disruptive tested change. Sensitivity does not convert the weights into a learned
or optimal ranking function.

## Topic and author evaluation

The 60-paper controlled-vocabulary set uses 36 development and 24 held-out test
cases, covers all 39 labels, includes 51 multi-label cases and four
`other/unknown` cases, and stores source locators. A dense label-prototype
threshold of 0.20 and cap of six labels were selected on development cases only.

| Method | Test micro precision | Test micro recall | Test micro F1 | Coverage |
|---|---:|---:|---:|---:|
| Controlled lexical | 0.6522 | 0.4839 | 0.5556 | 0.8750 |
| Dense prototype | 0.4175 | 0.6935 | 0.5212 | 0.9583 |

The lexical method remains the public path because it is inspectable and more
precise; the dense alternative has higher recall/coverage but substantial
prototype overreach. The author audit found no excluded-paper leakage, alias
collision, authorship mismatch, or wording that claimed availability,
endorsement, or supervisor suitability. Thirteen possible same-person pairs
remain unresolved for external identity confirmation.

## Persisted generated-output review

All 48 stored outputs (27 RAG answers, seven recommendations, 14 paper
artifacts) received one attributable AI review event. Fourteen artifacts and
seven recommendations are `ai_reviewed`; 27 historical RAG answers are
`needs_reprocess` because their original paper scope, audience, or word-limit
configuration cannot be reproduced safely. The review retained 269 citation
evidence locators. Event-chain verification covered 48/48 events, and a second
live pass created zero events and changed zero records. `ai_reviewed` is not
human approval.

## Performance and external-validity protocol

The validated full benchmark ran three process-cold and three warm repetitions
at concurrency one for each of 17 stages. All 102 samples include elapsed time,
processed units, success/failure, and process maximum RSS; aggregates are median
and linearly interpolated p95. The artifact records WSL2, AMD Ryzen 7 5800X,
16 logical CPUs, 3.8 GiB RAM, software/lock versions, corpus counts, unchanged
database SHA-256, clean source commit `5ccf22e`, and provenance digest
`61378b9a...`. All 102 samples succeeded. Three repetitions provide a coarse
p95 and cannot support a service-level objective, multi-user capacity claim,
or asymptotic scaling claim.

The external Europe PMC sanity check reacquired three pinned CC BY JATS/XML
documents, verified their license evidence, mapped them into the production
chunker contract, and produced 3/3 expected fixed lexical top-one matches. It
did not exercise the main PDF-ingestion path and is not cross-domain retrieval-
quality evidence.

## Prospective remediation-v2 protocol

The immutable v1 files above remain historical post-selection descriptions.
The source-first v2 protocol is a new, fixed execution designed to evaluate the
remediated selective-response and Finder contracts without tuning on held-out
outputs. Its scope is the current generation-linked **technical** corpus; it
records the independent public predicate but sets
`public_projection_evaluated=false`.

### Freeze and execution order

Each fresh frozen workspace uses the following order:

```bash
PYTHONPATH=backend .venv/bin/python data/evaluation/run_peer_review_remediation_v2.py prepare
PYTHONPATH=backend .venv/bin/python data/evaluation/run_peer_review_remediation_v2.py evaluate
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_peer_review_remediation_v2.py
```

`prepare` must precede any v2 retrieval or generation. It requires clean,
committed protocol/code/dataset inputs and a lock-valid Python environment,
verifies every source locator against SQLite, freezes code/corpus/retrieval/
generation identities and data splits, inventories the PDF/extraction/chunk
generation chain, and creates the deterministic OCR fixture. `evaluate` refuses
any changed identity, snapshots SQLite into a temporary database, reconciles
generation links fail closed, builds a temporary keyword representation, and
permits one `evaluate` invocation for that freeze/workspace. The first accepted
source candidate is the confirmatory execution. A subsequent full run is a
deterministic replication of the same locked protocol and cases; no retuning,
relabeling, case changes, or result selection is permitted. The final validator independently recomputes
case membership, metrics, all 5,000-replicate seeded cluster-bootstrap
intervals, manuscript macros, manifest contents, and exact package inventory
before writing/accepting the attestation.

### Fixed cases and permitted metrics

- **Ask:** 12 source-derived answerable cases and six named-paper exact-phrase
  absence probes, fixed keyword retrieval, top five, offline extractive model,
  and the already-fixed answerability threshold. The negative probes establish
  structural exact-phrase absence only, not semantic absence under paraphrase.
  Metrics cover answerability/abstention, exact gold-locator citations,
  citation completeness/utilization, and answer-point coverage.
- **Finder:** four development, five held-out test, and one sensitivity-only
  synthetic profile; paired evidence-only and full-Finder rankings share the
  same retrieval response. The weights are frozen. Candidate-specific template
  conformance and profile-field propagation are deterministic contract checks,
  not independent usefulness or feasibility judgments.
- **Topics:** four development and eight test paper cases contain positive-only,
  non-exhaustive source labels. Permitted results are known-positive recall,
  known-positive case coverage, per-label support/misses, and counts/share of
  unadjudicated predictions. Precision, F1, exact match, and false-positive
  interpretations are prohibited.
- **OCR:** one raster-only deterministic fixture invokes the production parser
  and Tesseract configuration. Tesseract is therefore a required system
  prerequisite for every full v2 reproduction, even though the historical TTLAB
  corpus itself recorded no OCR-processed pages. The fixture verifies that the OCR path runs against known
  fixture text; it does not estimate accuracy on TTLAB papers or scanned
  document populations.

### Evidence and release separation

Exactly one versionable location is permitted:
`artifacts/peer_review_remediation/v2/`. It has a closed flat-file allowlist and
contains structural IDs, hashes, labels, aggregates, macros, manifest, and
attestation. Full extractive answers, source snippets, generated Finder bodies,
and topic evidence text are required locally under
`tmp/restricted/peer_review_remediation/v2/` (or another ignored operator path)
and cannot be committed or released. The restricted-output manifest records
hash/size attestations; this is not independent proof of unseen content.

The two shuffled passes use the same AI procedure. Their disagreements and
repeatability are AI-silver evidence, not human inter-rater reliability. No v2
metric may be described as student benefit, supervisor approval, real-world
feasibility, novelty, semantic entailment, public-corpus effectiveness, or
general OCR accuracy.

The accepted package is bound to the clean source-candidate commit/tree that
the isolated workspace executed. A later evidence commit may contain only the
validated canonical package, retained content-free attestations, generated
manuscript evidence/PDFs, and closure documents. That evidence commit is not
called the reproduced source. Any protocol, dataset, source locator,
application, or manuscript-source change requires a new candidate freeze and
full execution.

## Error analysis and reporting rules

Error reports include extraction/structure, intent mismatch, lexical mismatch,
semantic mismatch, topic/identity error, over-broad expansion, ranking
diversity, corpus absence, off-topic support, citation error, evidence miss,
answer-point omission, feasibility uncertainty, and weak evaluation plan. A
zero category means no case was tagged by the defined procedure, not proof that
the failure mode cannot occur.

All tables must cite their machine-readable source. No metric may enter the
paper or thesis without its raw cases, configuration, input hash, and code path.
Inventory counts, test counts, and traceability counts are not reported as
accuracy. Human benefit, novelty, legal permission, and institutional approval
remain outside this offline protocol.

## Verification commands

```bash
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_retrieval_silver_v1.py
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_experiment
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_qa_faithfulness_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_recommendation_proxy_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_topic_author_silver_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_section_quality_silver_v1.py --evaluate-current
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review
PYTHONPATH=backend .venv/bin/python -m app.evaluation.external_sanity
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_peer_review_remediation_v2.py --static-only
```

The aggregate artifacts already committed under `artifacts/phase1` through
`artifacts/phase4` and `artifacts/phase6/external_sanity` are the evidence for
the results above. Re-execution must not overwrite them from a different corpus
without producing a new snapshot and manifest. Do not run the v2 `evaluate`
command as an ad-hoc validator or layout prerequisite; `make reproduce` executes
the freeze/evaluate/validate sequence in its detached full-corpus workspace.
