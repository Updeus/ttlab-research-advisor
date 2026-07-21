# Executed Research Methodology

## Study design and claim boundary

This project is an artefact-oriented design-science/engineering case study with
controlled offline evaluation. The artefact is a source-traceable research-
intelligence platform for one laboratory publication corpus. The study
implements the system, freezes its eligible corpus and retrieval
representations, evaluates the resulting components on versioned cases, and
retains raw decisions, rankings, configurations, hashes, and failure cases.

The study did not recruit human participants. Labels and formative judgments
were prepared by `codex-ai-review` and are identified as AI-reviewed silver
labels or AI-assisted proxy review. They are not human gold judgments,
independent assessor ratings, usability evidence, student validation, or
supervisor approval. Engineering tests establish implementation behaviour; they
do not establish retrieval or answer quality.

**Research aim.** Engineer and empirically characterize a reproducible platform
that converts a bounded laboratory publication archive into full-text discovery,
source-cited question answering, publication-derived topic/author exploration,
and explicitly labeled project-extension suggestions without conflating
provenance with correctness.

## Research questions

- **RQ1 — Corpus and traceability:** Can a heterogeneous laboratory archive be
  transformed into a defensible, page-aware corpus whose eligible chunks are
  covered one-to-one by fail-loud retrieval manifests?
- **RQ2 — Retrieval:** How do keyword, deterministic feature hashing, pinned
  learned-dense, heuristic hybrid, and development-tuned hybrid retrieval
  compare on a held-out AI-reviewed silver set, and which heuristic terms
  materially change rankings?
- **RQ3 — RAG evidence quality:** To what extent does the offline extractive
  answerer produce source-supported claims, correct and complete citations,
  answer-point coverage, and appropriate abstention?
- **RQ4 — Advisory and discovery outputs:** What does AI-assisted proxy review
  reveal about the evidence fidelity and limitations of thesis-extension
  recommendations, controlled topic labels, publication-derived author links,
  and persisted generated outputs?
- **RQ5 — Engineering readiness:** To what extent is the bounded artefact
  reproducible and reviewable on documented local hardware, externally
  format-compatible, and governed by privacy-minimizing, authenticated,
  accessible evidence interfaces without redistributing restricted PDFs?

## Objectives and contributions

The executed objectives were to: (1) establish a provenance-preserving corpus
and authoritative index contract; (2) add and compare lexical, feature-hashing,
and learned-dense retrieval; (3) evaluate RAG claims and citations rather than
equating a runtime grounding label with correctness; (4) evaluate advisory and
discovery outputs with explicit AI-review provenance; and (5) expose evidence,
review, freshness, security, and uncertainty through reproducible APIs and a
route-based frontend.

The contributions are deliberately bounded:

1. an integrated full-text research-intelligence artefact with persistent
   paper/chunk/page/section provenance and distinct fact, inference, and
   suggestion states;
2. an authoritative corpus/index design that prevents a bounded demo rebuild or
   stale database status from representing a partial index as complete;
3. controlled offline evaluations with raw failures, confidence intervals,
   ablations, and negative results across retrieval, QA, recommendations, and
   topic classification; and
4. a reproducibility and governance boundary that preserves local operation
   while excluding restricted full text, private histories, and secrets from a
   sanitized release.

No novel retrieval algorithm, demonstrated human advisory benefit, broad
external validity, or production-scale capacity is claimed.

## Units of analysis

Different questions require different units rather than one misleading global
sample size:

| Workstream | Primary unit | Executed sample |
|---|---|---:|
| Corpus integrity | catalogue record and eligible chunk | 134 records; 735 raw chunks |
| Section detection | source chunk | 40 silver cases |
| Retrieval | query | 50 cases: 30 development, 20 held-out test |
| RAG review | QA case, atomic claim, citation link, answer point | 50 cases; 400 checkable claims; 81 answer points |
| Recommendation proxy review | synthetic profile and ranked item | 28 profiles; 84 items per arm |
| Topic classification | paper case and label decision | 60 papers: 36 development, 24 test |
| Generated-output review | persisted output | 48 records |
| External sanity check | openly licensed document/query | 3 documents; 3 fixed queries |
| Performance | process-cold or warm repetition | 17 stages; 102 executed samples/RSS records |
| Remediation v2 | Ask case, synthetic Finder profile, positive-only topic case, OCR fixture | prospective frozen protocol: 18, 10, 12, and 1 respectively |

## Corpus snapshot, provenance, and eligibility

The source catalogue contains 134 records. Ninety-eight records have local PDF
content; 34 have no PDF URL, one acquisition ended in a network error, and one
was not found. PDF/title identity review found 96 matched records and two
possible metadata/PDF mismatches. The two mismatches and their 16 chunks were
excluded rather than silently attributed to the catalogue records. The 36
records without usable text remain visible as `needs_review` but are not
experimental retrieval items.

The historical-v1 frozen experimental snapshot is
`corpus-04a010207327069a`, SHA-256-derived
snapshot hash
`04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5`.
It contains 96 eligible papers and 719 eligible chunks from 735 raw chunks.
Every included chunk retains a stable ID, paper ID, page range, section label,
text hash, and extraction provenance. That historical snapshot used native PDF text;
OCR status is `not_requested` for all 134 records. OCR support and scanned-page
detection exist, but no OCR accuracy or latency is reported for this corpus.

This is the technical evaluation boundary, not a public corpus. Anonymous
metadata additionally requires approved review status, `published`, cleared
rights, and `metadata_only|searchable` access. Anonymous source text/search also
requires technical eligibility, approved extraction, a current extraction-to-
chunk generation chain, and a promoted public index generation. Unknown legacy
states fail closed, and a zero-record public projection does not fall back to
the technical corpus.

Section heuristics were checked on 40 source-backed silver cases. Current-label
accuracy was 0.900, labeled accuracy 0.8889, labeled coverage 0.900, macro
precision 0.8917, and macro recall 0.9040. The 199 eligible `Unknown` chunks are
retained because uncertainty is preferable to forcing an unsupported heading.

## System and representation design

The system has five cooperating layers:

1. **Acquisition and processing:** allowlisted discovery/download, PDF identity
   audit, page extraction, optional OCR, section detection, and deterministic
   chunking.
2. **Retrieval and intelligence:** SQLite keyword/FTS retrieval, 256-dimensional
   signed feature hashing, a 384-dimensional pinned learned encoder, hybrid
   ranking, extractive/offline or optional local generation, citation checking,
   recommendation, artifact generation, and topic/author exploration.
3. **Persistence and integrity:** SQLModel/SQLite records, immutable source
   hashes, immutable index generations with atomically promoted checksum-bound
   current pointers, authoritative manifests, generated-output review status,
   and append-only application-level review events with a hash chain.
4. **Service and interface:** FastAPI public/read and protected mutation routes,
   plus a React/Vite route-based interface that displays source locators,
   provider/model metadata, freshness, review state, and responsible-AI notices.
5. **Evaluation and release:** versioned silver sets, experiment runners,
   validators, statistical summaries, frontend/backend tests, document builds,
   and a sanitized allowlist-based release builder.

The feature-hashing baseline is not called a learned semantic model. Learned
dense retrieval uses `sentence-transformers/all-MiniLM-L6-v2` at revision
`826711e54e001c83835913827a843d8dd0a1def9`, with model artifact hash
`18309e334c0231266dcaba3f9b70f47e919b787190a3e5d22744b240048c0a7c`,
384 dimensions, deterministic overlapping tokenizer windows, mean pooling, and
L2 normalization on CPU. Both feature-hashing and dense manifests cover all
719 eligible chunks. A missing or stale dense model/index is reported as a
provider state; the system does not silently describe hashing as dense search.
Present-but-invalid pointers, payloads, manifests, configuration, or live
corpus identities fail rather than falling back to an older compatibility
mirror. Bounded/demo generations cannot update authoritative database status.

## Evaluation procedure

### Silver-label preparation

Each silver set preserves source identifiers, page/chunk locators, rationale,
reviewer type, timestamps, and review pass. One AI reviewer created judgments
from source material and later verified them in fixed-seed shuffled order. The
retrieval labeling procedure did not inspect system rankings. Creation and
verification disagreements were retained and adjudicated by the verification
pass. Consistency statistics describe repeatability of one AI procedure, not
human inter-rater reliability.

### Retrieval experiment

The retrieval set contains 50 questions across factual, methods, results,
limitations/future-work, metadata, topic/application, comparison, broad,
multi-paper, hard-negative, and out-of-corpus categories. Thirty development
cases were used for hybrid weight selection and sensitivity analysis; 20 test
cases were held out. All methods used the same corpus, query set, filters,
candidate-pool controls, and cutoffs. The experiment reports set Recall@3/5/10,
Hit@3/5/10, Precision@3/5/10, MRR, graded nDCG@10, and unanswerable false-
positive/abstention behaviour. Per-query rankings and scores are retained.

Development tuning selected keyword weight 0.10 and dense weight 0.80 with all
six heuristic terms enabled. Individual and cumulative ablations cover query
expansion, metadata, section, evidence, topic, and diversity adjustments;
neighboring weights were evaluated only on development cases. Test uncertainty
uses 10,000 fixed-seed query bootstraps. Tuned-vs-baseline query-level
differences use two-sided paired randomization and Holm-Bonferroni correction
over the experiment family.

### RAG evaluation

The offline extractive hybrid answers for 50 stratified cases were segmented
into atomic claims. Review recorded full/partial/no support, citation-link
correctness, citation completeness, answer-point coverage, unsupported general
knowledge, and answerability/abstention. Case-cluster bootstrap intervals use
10,000 repetitions. The local Ollama service was unavailable, so no local-model
quality, digest, quantization, or latency comparison is invented.

### Recommendation, topic/author, and output review

Twenty-eight synthetic profiles span interests, skills, time, project type,
data constraints, difficulty, and avoid-topics. For each profile, a same-query
evidence-only arm and the full deterministic Finder returned three ranked
papers. Two shuffled AI-review passes assessed relevance, source fidelity,
fact/future-work/gap/suggestion separation, novelty caution, feasibility,
scope, risk, skills, evaluation plan, and usefulness as an AI proxy. Default
recommendation weights were hand-authored, not learned; 22 configurations (the
default plus 21 zero/plus/minus-25% one-term perturbations) test ranking
sensitivity.

The topic study compares the retained controlled lexical vocabulary with a
pinned dense-prototype alternative over 39 labels. Threshold 0.20 and a six-
label cap were selected on the 36-case development split; 24 cases remained
held out. The associated author audit tests excluded-paper leakage, alias
collisions, authorship mismatches, and wording overclaim. It does not infer
availability or endorsement.

Finally, all 48 persisted historical outputs were inspected. Fourteen paper
artifacts and seven recommendation records were regenerated or verified and
marked `ai_reviewed`; 27 historical RAG answers lacked sufficient reproducibility
configuration and were conservatively marked `needs_reprocess`. Forty-eight
attributed review events were created, the hash chain verified, and a second
pass produced zero changes.

### Performance and external sanity

The following measurements are retained historical-v1 engineering evidence.
The committed full profile contains all 17 required stages, three process-cold
and three warm samples per stage, 102 RSS-bearing samples, and zero failures.
It ran at concurrency one on WSL2 with an AMD Ryzen 7 5800X, 16 logical CPUs,
and 3.8 GiB available RAM. The artifact is bound to clean source commit
`5ccf22e`, unchanged standalone-database SHA-256 `a8153f53...`, and provenance
digest `61378b9a...`. Dense indexing had cold median/p95
145.005/145.020 seconds, warm median/p95 66.169/134.066 seconds, and 751.5 MiB
peak process RSS; eight-route rendering had 12.496/12.807 and
12.463/12.631 seconds, respectively. OS caches were not flushed. These are
bounded single-machine latency/resource observations, not capacity, load, or
service-level evidence.

The external sanity harness reacquired three pinned CC BY JATS/XML articles
from the official Europe PMC API, verified embedded license evidence, mapped
them into the production chunker contract, and achieved 3/3 fixed lexical
top-one matches. It did not validate the main PDF-ingestion path, TTLAB
effectiveness, or cross-domain retrieval quality.

### Prospective remediation-v2 procedure

The v1 experiments above are retained as historical post-selection evidence.
The remediation-v2 protocol was authored source-first and freezes its code,
locked environment, generation-linked technical corpus, PDF/extraction/chunk
artifact inventory, source locators, datasets, split IDs, answerability rule,
Finder weights, OCR fixture/configuration, and bootstrap seed before retrieval
or generation. It records but does not exercise the independent public
projection.

Within each fresh freeze/workspace, the full isolated reproducer invokes
`prepare`, one `evaluate` invocation, then an independent validator. The first
accepted source candidate is the confirmatory run. A later full run is an
unchanged-protocol deterministic replication and must not retune, relabel, add
cases, or select among outcomes. `prepare` rejects dirty/uncommitted evaluation
sources and writes a freeze receipt. `evaluate` refuses any changed identity,
uses a temporary SQLite backup and keyword index, and separates structural
versionable outputs from operator-local rights-sensitive raw text. The
validator recomputes case membership, identities, metrics, 5,000-replicate
cluster-bootstrap intervals, deterministic manuscript macros, and the exact
flat package inventory before accepting an attestation.

The fixed workstreams cover selective Ask answerability/citation/answer-point
behaviour, paired evidence-only/full-Finder ranking and contract behaviour,
known-positive topic recall/coverage, and one deterministic scanned-fixture OCR
path. The two shuffled passes are repeated applications of the same AI-authored
procedure. They are AI-silver repeatability evidence, not human inter-rater
reliability, semantic entailment, public-projection quality, student usefulness,
supervisor validation, practical feasibility, novelty, or corpus OCR accuracy.
Results enter a manuscript only through the completed, independently validated
canonical package under `artifacts/peer_review_remediation/v2/`; a layout-only
`not run` package is not experimental evidence.

## Research-question traceability

| RQ | Method | Authoritative evidence | Historical-v1 result and bounded conclusion |
|---|---|---|---|
| RQ1 | Identity audit, eligibility freeze, section silver review, manifest verification | `artifacts/phase1/phase1_evidence.json` and index manifests | 96 papers/719 chunks are eligible; feature-hashing and dense indexes cover 719/719. Two mismatched PDFs and 36 no-text records are excluded. |
| RQ2 | 30/20 development/test silver retrieval experiment, ablations, bootstrap, paired tests | `artifacts/phase2/retrieval/` | Keyword led held-out MRR (0.9474); tuned hybrid MRR was 0.8596. No tuned-vs-baseline contrast survived family correction. Hybrid superiority is not demonstrated. |
| RQ3 | Atomic-claim/citation/answer-point AI review with clustered bootstrap | `artifacts/phase3/qa/` | Claim support was high (0.995), but citation correctness was 0.625, strict answer-point coverage 0.1358, and all four unanswerable cases failed to abstain. Traceability did not ensure completeness. |
| RQ4 | Synthetic-profile proxy review, topic split comparison, author audit, full persisted-output review | `artifacts/phase4/` | Full-Finder relevance exceeded evidence-only by only 0.0238 (95% CI -0.0238 to 0.0714); lexical topics traded recall for higher precision; 27 stale RAG answers require reprocessing. No human usefulness claim follows. |
| RQ5 | Security/privacy/accessibility tests, source-candidate reproduction/release verification, full performance profile, external sanity | code/tests, `docs/FRONTEND_REQUIREMENTS.md`, `artifacts/phase6/`, final reproduction manifest | The historical validated 17-stage profile completed 102/102 samples without failure. Current source-candidate reproduction/release acceptance is not inferred from that run; its source and later evidence commit identities belong only in `docs/peer_review_readiness/FINAL_READINESS_REPORT.md`. Public inputs are transient and mutations authenticated. Automated accessibility regressions passed but do not establish WCAG conformance or assistive-technology usability; the three-document JATS/XML check is only a chunker-contract sanity result. |

## Validity, ethics, and reproducibility controls

- **Construct validity:** source traceability is not factual correctness;
  lexical support may over-credit copied but off-topic text; AI proxy usefulness
  is not student usefulness; three-run p95 is coarse.
- **Internal validity:** the same AI system prepared and verified silver labels;
  heuristic queries and rubrics can bias outcomes; fixed seeds and raw decisions
  make the procedure auditable but do not remove that bias.
- **External validity:** the corpus is one laboratory, the held-out cohorts are
  small, and the three-document Europe PMC check is deliberately narrow.
- **Reproducibility validity:** hashes, manifests, pinned model revision,
  configurations, per-case results, and fail-loud validators reduce accidental
  drift. Exact corpus reproduction still requires separately authorized PDFs
  and local derived state.

TTLAB authorization supports the project and use of the laboratory corpus. It
does not imply ethics-board approval, copyright ownership, public-deployment
approval, or permission to redistribute every third-party PDF. Public question
and student-profile inputs are transient by default. Restricted PDFs, full-text
databases/indexes, private prompts, histories, and secrets are excluded from the
sanitized release.

Codex/LLM assistance materially contributed to repository audit, code and test
preparation, silver-label preparation, analysis, documentation, figures, and
manuscript editing. The datasets retain AI reviewer identity and limitations.
Institutional and venue attestations that cannot be established by repository
evidence remain in `docs/EXTERNAL_SUBMISSION_CHECKS.md`.
