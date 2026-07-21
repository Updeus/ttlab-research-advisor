# Final peer-review readiness report

Report type: **AI-assisted remediation and verification report; not human peer
review**.

Repository: `https://github.com/Updeus/ttlab-research-advisor`

Baseline audited: branch `main`, commit
`b561fa73c1de50569d7e76261b2aa37195524c21`, 2026-07-20.

Prospective remediation-v2 evaluation source: commit
`0d4b9bdcb657034beab5c288ab174983eb0760e3`.

Verified sanitized release candidate: commit
`1411985038c1152a0fe4e7063d93f080acffdbf7`, archive
`ttlab-research-advisor-0.1.0-remediation-1411985038c1.tar.gz`, SHA-256
`5ac3a3a19900c1ffcd5e6b33540754d2a59ced2451f0983d25331ab6628e801c`.

The result is suitable for **close supervisor review**. It is not a declaration
of formal-submission readiness, public-deployment readiness, human validation,
research-ethics approval, or third-party PDF redistribution permission.

## 1. Executive disposition

The audit opened 67 issues. The final disposition is 61 fixed, one partially
fixed, two human-required, and three environment-blocked. No negative result was
removed to obtain that disposition. In particular, historical strict QA
answer-point coverage of 0.135802 remains in both manuscripts, and the new
prospective result does not establish a causal improvement.

The hard manuscript constraints are now met: the IEEE paper is six Letter pages
including 21 references, and the thesis is 88 A4 pages including 38 references.
The additional thesis content is substantive methodology, architecture,
implementation, frontend, evaluation, error-analysis, governance, and
reproducibility material rather than blank-page or spacing inflation.

The repository now has fail-closed corpus/index contracts, attributable
append-only review events, explicit technical-versus-public projections,
source-versus-suggestion separation, a frozen prospective evaluation package,
and deterministic manuscript gates. These are engineering and reproducibility
results. They do not establish that generated prose is factually correct or
entailed, that a recommendation is novel or feasible, or that a researcher is
available to supervise it.

## 2. Baseline versus final state

| Measure | Audit baseline | Final state | Interpretation |
|---|---:|---:|---|
| Open audit issues | 67 | 0 unclassified | Every row has a terminal or partial disposition |
| Fixed issues | 0 | 61 | Repository-verifiable closure evidence is recorded in the remediation matrix |
| Partially fixed | 0 | 1 | `QA-001`: evaluation and controls improved, effectiveness remains weak |
| Human-required | 2 | 2 | Rights/publication and formal-submission decisions cannot be invented |
| Environment-required | 3 | 3 environment-blocked | Repository prerequisites are narrowed; production infrastructure remains external |
| Paper pages | 8 | 6 | At-most-six-page requirement met without changing IEEE margins or body font |
| Paper cited references | 29 | 21 | Within the documented approximate 18--22 target |
| Thesis pages | 74 | 88 | At least 75 substantive pages |
| Thesis bibliography entries | 32 shared entries at baseline | 38 thesis entries | Final bibliography count from `build/thesis.bbl` |
| Backend tests | 255 passed | 407/407 passed across 43 files in eight bounded shards | Zero failures, errors, or skips; engineering evidence only |
| Frontend tests | 20 in 6 files | 67 passed | Includes route, state, review, contract, and automated accessibility checks |
| Frontend E2E | 6 passed | 9 passed | Browser navigation and principal workflows |
| Frontend production build | passed | passed | Vite production build |
| Frontend dependency audit | 0 reported vulnerabilities | 0 reported vulnerabilities | `npm audit --audit-level=high`; not a penetration test |
| Documentation validation | passed | passed: 45 Markdown files and 22 local links | Zero validation errors |
| Exact release/reproduction gate | failed before final manifest | passed from clean candidate `1411985038c1`; two byte-identical builds | Archive verification covered 450 members and 448 checksummed entries |

The audit-baseline technical corpus contained 134 catalogue records, 98 local
PDFs, 735 raw chunks, 96 technically eligible papers, and 719 technically
eligible chunks under snapshot `corpus-04a010207327069a`, SHA-256
`04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5`.
The post-remediation v1-form reexecution and accepted prospective package bind
the same eligible 96/719 counts to the later snapshot
`corpus-f4638c633bea82b0`, SHA-256
`f4638c633bea82b02df4e6ff5f8540020f3ca29bd7493a3465036a37582c7ab1`.
Equal counts do not make those snapshot identities interchangeable.
Two title/PDF mismatches remain excluded, 36 records remain in a needs-text or
needs-review partition, and 199 eligible chunks retain `Unknown` section labels.
Those exclusions and unknowns are visible rather than silently coerced.

## 3. Issue accounting

### By severity

| Severity | Baseline open | Fixed | Partially fixed | Human-required | Environment-blocked |
|---|---:|---:|---:|---:|---:|
| BLOCKER | 6 | 4 | 0 | 2 | 0 |
| CRITICAL | 8 | 8 | 0 | 0 | 0 |
| HIGH | 28 | 26 | 1 | 0 | 1 |
| MEDIUM | 24 | 22 | 0 | 0 | 2 |
| LOW | 1 | 1 | 0 | 0 | 0 |
| **Total** | **67** | **61** | **1** | **2** | **3** |

### By fixability

| Fixability | Baseline | Final disposition |
|---|---:|---|
| `AUTO` | 9 | 9 fixed |
| `AUTO_CONSERVATIVE` | 44 | 44 fixed |
| `AUTO_EXPERIMENT` | 9 | 8 fixed; `QA-001` partially fixed |
| `HUMAN_REQUIRED` | 2 | 2 human-required |
| `ENVIRONMENT_REQUIRED` | 3 | 3 environment-blocked after repository-side narrowing |

The 61 fixed rows span 59 exact matrix categories. `Admin review` and
`Reproduction pipeline` each contain two fixed rows; one row was fixed in each
of: API/UI contract, Academic writing, Accessibility, Authors and metadata,
Bibliography accuracy, Build diagnostics, Citation grounding, Corpus inclusion,
Credential minimization, Cross-revision consistency, Database integrity,
Dependency maintenance, Derived artifacts, Derived-state invalidation, Document
accessibility and presentation, Documentation consistency, Editorial publication
boundary, Evaluation dashboard, Frontend and requirements, Frontend completeness,
Frontend request integrity, Frontend resilience, Frontend state, Generated
artifacts UI, IEEE PDF profile, IEEE paper, IEEE paper structure, Index atomicity,
Ingestion consistency, Manuscript scope, Metadata correction UI, Metadata
provenance, Methodology and leakage, OCR reproducibility, PDF ingestion and
corpus coverage, Paper browser, Paper provenance, Paper statistical clarity,
Provider abstraction, Provider metadata, Provider reproducibility and resource
control, Reproducibility, Research questions, Retrieval and RAG, Retrieval
defaults, Review completeness, Runtime/repository boundary, Statistical
reporting, Terminology and API, Thesis, Thesis Extension Finder, Thesis Extension
Finder UI, Thesis Extension Finder evaluation, Thesis literature and methodology,
Topic evaluation, Typesetting polish, and Validation.

The authoritative per-issue evidence, dependencies, verification command, and
status remain in `REMEDIATION_MATRIX.csv`; this report does not replace that
machine-readable register.

## 4. Evaluation evidence and scientific boundary

All labels in this section are source-derived AI-silver judgments. The audit
baseline at `b561fa73...`/`corpus-04a...` remains preserved in `BASELINE.md`,
`AUDIT_REPORT.md`, the remediation matrix's original evidence, and the dated
project-evidence log. The current manuscripts instead consume a separately
reexecuted v1-form evidence set at source `73092e48...`/`corpus-f463...`, plus
the prospective v2 package. The audit-baseline QA run had 400 claims, citation
correctness 0.625, citation utilisation 0.592, coverage 11/81, and 0/4
unanswerable abstentions; its Finder comparison returned 84 items in each arm
and had a conditional full-minus-evidence relevance estimate of about 0.0238.
Those values are historical audit evidence, not silently overwritten current
results. The shuffled
second pass measures repeatability of one AI procedure, not independent-human
inter-rater agreement. Bootstrap intervals quantify case/profile/paper sampling
only; they exclude corpus-selection, label, and reviewer uncertainty.

### 4.1 Post-remediation v1-form retrieval

The historical held-out retrieval test contained 19 answerable queries plus one
unanswerable query. The principal point estimates are:

| Mode | MRR | Set Recall@10 | Boundary |
|---|---:|---:|---|
| Keyword FTS | 0.947368 | 1.000000 | Strongest historical point estimate |
| Feature hashing | 0.587719 | 0.703509 | Signed 256-dimensional feature hashing; **not learned semantic retrieval** |
| Pinned learned dense | 0.938596 | 0.989474 | `all-MiniLM-L6-v2`, 384 dimensions |
| Dev-tuned hybrid | 0.912281 | 0.978070 | No corrected comparison established superiority |

Every mode answered the one unanswerable query, so the historical abstention
result remained negative. Build, index-coverage, or test counts are not
effectiveness evidence.

### 4.2 QA: post-remediation v1-form and prospective v2

| Measure | Post-remediation v1-form | Prospective v2 held-out test |
|---|---:|---:|
| Cases | 50 | 12 (8 answerable, 4 unanswerable) |
| Strict answer-point coverage | 11/81 = **0.135802** | 3/16 = **0.187500**; cluster-bootstrap 95% CI [0.062500, 0.300000] |
| Citation measure | AI-silver citation correctness 0.652695 | exact predeclared locator precision 1/11 = 0.090909; CI [0.000000, 0.187500] |
| Citation completeness | 1.000000 structural | 11/13 = 0.846154; CI [0.692308, 1.000000] |
| Unanswerable abstention | 1/4 = 0.250000 | 0/4 = 0.000000 |
| False-positive rate on unanswerable cases | 3/4 | 4/4 = 1.000000 |

The prospective strict coverage is numerically 5.17 percentage points above the
historical 0.135802 result. It is **not a paired improvement estimate**: v1 and
v2 use different frozen cases, denominators, locator rules, and evaluation
protocols. The intervals overlap, no paired test was defined, and the v2 system
failed to abstain on every held-out unanswerable case. `QA-001` is therefore
`partially_fixed`, not fixed. The improvement is in protocol rigor, claim
decomposition, exact-locator accounting, and visibility of failure—not
demonstrated answer quality.

Source traceability in either run means inspectable paper/chunk/page/section
locators and recorded provenance. It is not semantic entailment, factual
correctness, or completeness.

### 4.3 Thesis Extension Finder

The post-remediation v1-form Finder run used 28 synthetic profiles.
Evidence-only ranking returned all
84 requested top-three slots; full Finder returned 67/84, leaving 17 explicit
shortfalls. With missing slots scored as zero, the full-minus-evidence relevance
change was -0.035714, bootstrap 95% CI [-0.119048, 0.047619]. Full-output source
fidelity passed 67/67 and fact/future-work/gap/suggestion separation passed
66/67, but feasibility and AI-proxy usefulness each passed 0/67. This is a
negative result, not evidence that the projects are infeasible.

The prospective v2 held-out test contained five synthetic profiles:

| Measure | Evidence-only | Full Finder | Paired full-minus-evidence |
|---|---:|---:|---:|
| Hit@3 | 1.000000 | 0.800000 | -0.200000; CI [-0.600000, 0.000000] |
| MRR | 0.666667 | 0.600000 | -0.066667; CI [-0.600000, 0.466667] |

Candidate-specific template conformance, full constraint-contract fidelity,
source-fact/suggestion separation, and retention of unknown implementation time
were each 0.800000 on the five test profiles. These are contract/proxy results,
not student usefulness, novelty, data-access, workload, practical-feasibility,
or supervisor-fit evidence. The evidence-only baseline remained at least as
strong on the small held-out ranking sample.

### 4.4 Topics and OCR

The v2 topic test used eight positive-only, source-derived test cases. Known-
positive micro recall was 0.750000, cluster-bootstrap 95% CI [0.454545,
1.000000]; all-known-positive case coverage was 0.625000, CI [0.250000,
1.000000]. Half of returned predictions were outside the non-exhaustive
positive list (unadjudicated share 0.500000, CI [0.388889, 0.642857]). Because
unlisted labels were not adjudicated as negatives, precision, F1, exact-match,
and false-positive claims are intentionally absent. The run does not validate
author expertise or availability.

The OCR experiment exercised the production parser twice on a deterministic,
one-page raster-only fixture. Character error rate and word error rate were both
0.000000, the normalized text matched exactly, and both runs reproduced the
same sanitized output. This is pipeline-fixture evidence only; it is neither a
TTLAB-corpus OCR accuracy estimate nor a scanned-document prevalence estimate.

### 4.5 Performance

The validated historical full local profile contains 17 named stages, 102
timing/RSS samples, and zero recorded failures. It was executed at process
concurrency one on one WSL2 host; OS caches were not flushed. The environment
used `torch 2.13.0+cpu` and the dense index command explicitly selected CPU.
The evidence therefore supports local process-cold/warm descriptive timings,
not load, arrival-rate, tail-latency, saturation, service-level, or GPU claims.
Its validation provenance SHA-256 is
`2a71252db4f5722556cf1b03f8bbe3b2dee9b0d229b68de79fa20e8f4d2ed605`.

## 5. Remediation-v2 package, identities, and recovery

### 5.1 Frozen identity

| Item | Value |
|---|---|
| Evaluation ID | `peer-review-remediation-v2` |
| Evaluation source commit | `0d4b9bdcb657034beab5c288ab174983eb0760e3` |
| Technical snapshot ID | `corpus-f4638c633bea82b0` |
| Technical snapshot SHA-256 | `f4638c633bea82b02df4e6ff5f8540020f3ca29bd7493a3465036a37582c7ab1` |
| Eligible papers/chunks | 96 / 719 |
| Frozen QA/Finder/topic cases | 18 / 10 / 12 |
| Python lock SHA-256 | `93e43a941f8ca2bd25124c83360b54ff6f2109e575f3abefb211a7383b8058eb` |
| Frozen runner SHA-256 | `ce4466564ed7fa19c95b9b8f348bf4fb43c522836de3008f10a70ab8ffc90b44` |
| Frozen validator SHA-256 | `1de537ad8a0a2b052f485e52f7fd681680311bfe398990ef818e1860cfc210ca` |
| Freeze-receipt SHA-256 | `00c7d2541a9a88e3092cece6f3bb4fb239700c79c2fcb307f9e43b23d709d9f3` |
| Manifest SHA-256 | `bdc8e8b289d36834479f7bcc1c2efc9857b9812171dd3d4df7f2bff6680e18d9` |
| Versionable inventory SHA-256 | `2d8c636d2626286918da45ed99307dc7d2b02dfc3d1987366267cab370afd87c` |
| Validation report SHA-256 | `392761d37d4c55787e41174f921bba1fe38b2a33f743866956b912d5596b61de` |
| Validation-attestation SHA-256 | `f6d320bc246666bd19e7c6642c49e40b53d3acb3b52a789599e1eb3a290f34b7` |

The canonical directory contains exactly 17 versionable files: the freeze
receipt; manifest; validation attestation; manuscript macros; OCR result; QA
metrics, structural raw projection, two shuffled reviews, and disagreements;
Finder metrics, structural raw projection, two shuffled reviews, and
disagreements; and topic metrics and predictions. The manifest records 14
generated outputs; adding the receipt, manifest itself, and attestation gives
the 17-file canonical inventory. No full restricted passage text is included.

Three full raw files were retained outside the versionable package and are
required for a new strict recomputation:

| Restricted file | Bytes | SHA-256 |
|---|---:|---|
| `qa_full_raw_v2.jsonl` | 701006 | `104b63727bf259225eb97c6498d28febf7f470d7e0c860f962d3affb74b35c93` |
| `finder_full_raw_v2.jsonl` | 491507 | `f23e3d6eb13a45b766df10e8b8359b0a41c37ea32ea4261e1b65eb51d1ef07b8` |
| `topic_full_raw_v2.jsonl` | 52037 | `7d1377c5f8c8b3bd478cd7ff58043d898451321bfa6bf322f810f2137c3bfdb4` |

The strict attestation records that those local restricted files were checked
against the frozen IDs, splits, structural projections, source locators, and
recomputed aggregate metrics. A later `--versionable-only` run can verify every
distributed filename/hash and recompute structural aggregates, but cannot
independently re-prove the absent restricted text; it verifies the retained
strict attestation instead.

### 5.2 Packaging recovery without evaluation reexecution

The one prospective `evaluate` invocation completed all case execution and
metric generation, then stopped during manifest assembly because the runtime
provenance representation contained a redundant technical-scope field and the
Finder source identity serialized cited chunks rather than the complete paired-
retrieval locator set expected by the frozen checker. The evaluation was not
invoked again.

The bounded finalizer preserved originals, performed only those two
representation normalizations, assembled the manifest, and ran the frozen
strict validator. It did not execute cases, change labels, rescore results, or
change aggregate metrics. The content-free recovery receipt records:

| File | Original SHA-256 | Normalized SHA-256 | Change |
|---|---|---|---|
| `qa_raw_outputs_v2.jsonl` | `a1247dff6cf6710855dfae83088ac94a6b53309b341e1724b273c36269e4c017` | `519981929b4f554fa50f85c7184401d9246a1d643303534036f6d4b671ded6dd` | Removed redundant `corpus_identity.scope` from 18 records |
| `qa_full_raw_v2.jsonl` | `746d0fb0a7cd3289c0842085a7f0e118dbef3ed01e65742f10e233dbe6b3a238` | `104b63727bf259225eb97c6498d28febf7f470d7e0c860f962d3affb74b35c93` | Same representation-only normalization |
| `finder_raw_outputs_v2.jsonl` | `4b356ddd1653412e0441e3240814751c8ef0344aa58eab3ef671fb3ee21b0fb0` | `c7d73bde28470a17c3a438e3916a53b91eb7e380916252e7f397a87b2d8be1b8` | Removed redundant scope and restored complete paired-retrieval locators for 10 records |
| `finder_full_raw_v2.jsonl` | `25de0cdeacc89c134f84b370d5563ab22dc1d1aa1bb971919b9914be4cd79287` | `f23e3d6eb13a45b766df10e8b8359b0a41c37ea32ea4261e1b65eb51d1ef07b8` | Same representation-only locator correction |

The recovery receipt status is `PASS`, with
`evaluation_reexecuted=false`, `case_outputs_rescored=false`, and
`labels_or_metrics_changed=false`.

## 6. Software and frontend closure

The remediation established these repository-level invariants:

- authoritative indexes are generation-addressed and fail closed when partial,
  stale, differently scoped, or inconsistent with database status;
- demo indexes cannot overwrite the active authoritative generation;
- extraction, chunks, indexes, evaluations, generated outputs, and review
  events carry source/configuration/provider/code identities appropriate to
  their layer;
- malformed author/parser artifacts are repaired only from repository/source
  evidence, while unresolved same-person pairs remain unresolved;
- the public projection is separate from technical corpus eligibility and may
  legitimately be empty until rights and editorial gates pass;
- review events are attributed, append-only, hash chained, and idempotent for
  the same protocol/payload/decision while preserving later or human state;
- API and UI contracts distinguish source facts, paper-stated future work,
  inferred gaps, system suggestions, AI-silver review, and human review;
- profile inputs are non-persistent by default, review mutations require the
  protected route, and secrets are not supplied as committed defaults.

The frontend final checks report 67 passing unit/component/accessibility tests,
a passing production build, 9 passing browser E2E scenarios, and zero high-level
`npm audit` findings. Principal routes expose loading, empty, error/retry,
provider-offline, stale-index, and review-state behavior; deep links and browser
navigation are stable; evidence locators and generated/source distinctions are
visible. Automated axe smoke checks are regression evidence only and do not
establish complete WCAG conformance or usability with assistive technology.

## 7. Manuscript result and visual inspection

### IEEE paper

- Final PDF: 6 Letter pages, including all references.
- Cited references: 21 `\\bibitem` entries.
- Title/author/subject/keywords metadata are populated.
- `qpdf --check` passed; fonts are embedded; no Type 3 fonts were observed.
- The final build log contains no undefined citation/reference, missing figure,
  LaTeX fatal error, missing-character, or overfull-box finding.
- All six rendered pages were visually inspected at readable scale. Tables and
  the two diagrams are legible, content is not clipped or overlapped, negative
  evidence remains prominent, and the bibliography ends on page 6. The lower
  portion of the final reference page is unused; this is visible whitespace,
  not font/margin/spacing abuse or hidden evidence.

### Thesis

- Final PDF: 88 A4 pages.
- Bibliography: 38 `\\bibitem` entries.
- `qpdf --check` passed; fonts are embedded; no Type 3 fonts were observed.
- The post-fix build log contains no undefined citation/reference, missing
  figure, LaTeX fatal error, missing-character, or overfull-box finding.
- All 88 pages were rendered and inspected through six contact sheets, with
  individual inspection of the front matter, contents/lists, changed results
  pages, architecture/flow figures, frontend screenshots, code/schema/API
  listings, traceability appendix, reproducibility appendix, bibliography, and
  final page. No blank-page inflation, clipping, overlapping objects, unreadable
  added table/listing, or missing final-page content was observed. Normal partial
  pages at chapter boundaries remain.

Both PDFs report `Tagged: no`. The repository therefore makes no tagged-PDF,
PDF/UA, or complete document-accessibility claim. Figure descriptions remain in
source for a venue/institution toolchain capable of preserving them.

## 8. Remaining external items

### Human-required

1. **RIGHTS-001 (BLOCKER):** TTLAB authorization establishes project and
   laboratory-corpus use only. It is not university research-ethics approval,
   public-deployment approval, or blanket third-party PDF redistribution
   permission. Public operation needs a per-paper rights/editorial ledger,
   accountable institutional ownership, and real correction/retention/incident
   rules. Until then, the fail-closed public projection may remain empty.
2. **SUBMISSION-001 (BLOCKER):** the author/supervisor/institution must approve
   exact front matter, title and author order, affiliations, acknowledgements,
   funding/COI, target IEEE venue/profile, copyright notice, and venue AI-use
   compliance. Venue PDF eXpress or equivalent external checking remains a real
   submission step.

No human participants were recruited. Any later student/supervisor usefulness,
accessibility-usability, or practical-feasibility study first requires a real
institutional ethics determination and approved protocol. This is future work,
not evidence claimed by the current project.

### Environment-blocked

1. **SECURITY-001 (HIGH):** production use still needs infrastructure-level
   DNS/rebinding controls and isolation/sandboxing of untrusted PDF parsing.
   Repository validation, size/page limits, safe paths, and conservative
   failures narrow the exposure but cannot prove a deployment sandbox.
2. **OPS-001 (MEDIUM):** multi-process production operation still needs an
   explicit database contention, backup, monitoring, and recovery policy.
   Single-writer local SQLite behavior is adequate only for the bounded local
   demonstration.
3. **RATE-001 (MEDIUM):** process-local throttling is not a distributed
   concurrency budget. A public deployment needs trusted-proxy configuration
   plus shared rate/concurrency enforcement and monitoring.

These items do not justify building production-scale infrastructure for the
thesis artifact. The manuscripts instead narrow their claims to the verified
local/offline boundary.

## 9. Current-checkout versus evaluated-candidate boundary

The v2 results belong to evaluation commit
`0d4b9bdcb657034beab5c288ab174983eb0760e3`, not to an unqualified “latest
database” state. The evaluation copied a checkpointed source database with
SHA-256 `5ea480590fe588b2539d06a5c438d195b80dff4abdb81923b6c900f6450ac291`
into a temporary run, used an isolated rebuilt keyword index, and did not mutate
the tracked database. At report preparation, the active `data/papers.db` byte
hash was `00de01982f4720d26f9f3d8453922fe688f1360b153aec742ee20a7eb31e9875`;
it must not be substituted for the evaluated database identity.

The current reproduction script also postdates the evaluated commit: it adds a
fail-closed call to `scripts/finalize_peer_review_remediation_v2.py` for the one
recognized post-evaluation packaging failure. That difference is disclosed,
not folded into the evaluation claim. The frozen runner and validator remain
identified by the hashes above. On the current checkout, the versionable
validator passes all 17 canonical files, exact frozen IDs/splits, AI-silver
boundaries, aggregate recomputation, manifest identity, and the retained strict
attestation. It explicitly reports that its current mode cannot independently
repeat the restricted-raw check. The original strict attestation is the record
that binds the evaluated candidate to the three restricted full-raw hashes.

The sanitized release gate was run separately from clean release-candidate
commit `1411985038c1152a0fe4e7063d93f080acffdbf7`. Two isolated builds completed
in approximately 16 seconds each and produced byte-identical archives,
manifests, and adjacent checksum files. Each archive verified 450 members and
448 internal checksum entries. The release manifest records the 17-file v2
package as `source_commit_tracked`, with source-path presence, tracked status,
and byte equality all true. This report records that result after the release
build; therefore the subsequent report-only closure commit is intentionally not
represented as the archive's source commit. The archive proves the named clean
candidate, avoiding a self-referential claim that an archive contains its own
later report hash.

Consequently:

- manuscript numbers are tied to the named v1 or v2 artifacts, not recomputed
  implicitly from the active database;
- current application/reproduction changes may improve invariants without
  retroactively changing a frozen metric;
- a new full run from the current checkout would be a new experiment identity,
  not byte-for-byte reexecution of v2;
- exact strict reproduction requires lawful access to the matching local PDFs,
  the matching source database snapshot, the pinned dense-model cache, and the
  restricted raw boundary.

## 10. Final verification summary

| Gate | Result |
|---|---|
| Remediation-v2 `--versionable-only` validation | PASS; 17 files, 18 QA, 10 Finder, 12 topic IDs/splits exact |
| Backend test suite | PASS; 407/407 collected tests across 43 files in eight 60-second-bounded shards; 0 failures/errors/skips; 168.16 s summed pytest runtime |
| Frontend tests | PASS; 67 |
| Frontend build | PASS |
| Frontend E2E | PASS; 9 |
| Frontend high-level dependency audit | PASS; 0 reported vulnerabilities |
| Paper build/validator | PASS; 6 pages, 21 references |
| Thesis frozen assets/build/validator | PASS; 88 pages, 38 references, no material overfull box |
| PDF structural checks | PASS for both PDFs |
| Rendered visual inspection | PASS with the limitations in Section 7 |
| Documentation validation | PASS; 45 Markdown files, 22 local links, zero errors |
| Exact final release/reproduction | PASS; two byte-identical builds from clean candidate `1411985038c1`, SHA-256 `5ac3a3a19900c1ffcd5e6b33540754d2a59ced2451f0983d25331ab6628e801c` |
| `git diff --check` | PASS at the release candidate and before the report-only closure commit |

## 11. Bounded reproduction and verification commands

Every long-running command below has an explicit wall-clock bound. Run from the
repository root. An exit status of 124 or 137 is a timeout failure, not a pass.

### Frozen v2 package and tests

```bash
timeout --signal=TERM --kill-after=30s 2m \
  env PYTHONPATH=backend .venv/bin/python \
  data/evaluation/validate_peer_review_remediation_v2.py --versionable-only

timeout --signal=TERM --kill-after=30s 30m \
  env PYTHONPATH=backend .venv/bin/python -m pytest

timeout --signal=TERM --kill-after=30s 10m npm --prefix frontend test
timeout --signal=TERM --kill-after=30s 10m npm --prefix frontend run build
timeout --signal=TERM --kill-after=30s 15m npm --prefix frontend run test:e2e
timeout --signal=TERM --kill-after=30s 5m \
  npm --prefix frontend audit --audit-level=high
```

### Manuscripts and documentation

```bash
timeout --signal=TERM --kill-after=30s 10m make paper
timeout --signal=TERM --kill-after=30s 10m make thesis-assets-frozen
timeout --signal=TERM --kill-after=30s 15m make thesis-compile
timeout --signal=TERM --kill-after=30s 5m make docs-validate
timeout --signal=TERM --kill-after=30s 5m \
  .venv/bin/python scripts/validate_manuscripts.py

qpdf --check build/ieee-paper.pdf
qpdf --check build/thesis.pdf
pdfinfo build/ieee-paper.pdf | rg '^(Title|Author|Pages|Tagged):'
pdfinfo build/thesis.pdf | rg '^(Title|Author|Pages|Tagged):'
rg -c '^\\bibitem' build/ieee-paper.bbl
rg -c '^\\bibitem' build/thesis.bbl
rg -n -i \
  'Citation .* undefined|Reference .* undefined|There were undefined references|Overfull \\hbox|LaTeX Error|Emergency stop|Fatal error|Missing character' \
  build/ieee-paper.log build/thesis.log
git diff --check
```

For the final `rg` log scan, exit 1 with no output means no prohibited pattern
was found and is the expected result.

### New isolated full reproduction

This command creates a **new** experiment/release identity from the checked-out
commit. It requires lawful local corpus access and a locally cached pinned dense
model. It does not claim to regenerate the already frozen v2 bytes if the active
database or commit differs from the identities in Section 5.

```bash
TTLAB_REPRO_WORK="/tmp/ttlab-reproduce-$(date -u +%Y%m%dT%H%M%SZ)-$$"
TTLAB_REPRO_RETAIN="/tmp/ttlab-reproduce-retained-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test ! -e "$TTLAB_REPRO_WORK"
test ! -e "$TTLAB_REPRO_RETAIN"
timeout --signal=TERM --kill-after=30s 60m \
  scripts/reproduce_all.sh \
  --mode full \
  --work-dir "$TTLAB_REPRO_WORK" \
  --source-db data/papers.db \
  --retain-dir "$TTLAB_REPRO_RETAIN" \
  --release-version 0.1.0-remediation-final
```

If exact v2 strict recomputation is required, first restore the authorized
source database whose checkpoint hash is recorded in Section 9 and place the
three restricted raw files with the exact hashes in Section 5 in the configured
operator-local restricted directory. The versionable repository deliberately
does not contain enough restricted text to manufacture that state.

## 12. Final readiness assessment

The repository has moved from “remediation-focused supervisor review only” to
**close supervisor-review readiness**. The software is coherent and demoable;
the hard manuscript page/reference constraints are met; evaluation artifacts
are identity-bound; negative and null evidence is retained; and source,
suggestion, AI-silver, human-review, technical-corpus, and public-projection
boundaries are explicit.

External peer review would still be high risk if the paper were read as an
effectiveness or deployment claim. The strongest defensible contribution is the
architecture and reproducible evidence-boundary method. QA answer completeness,
exact citation targeting, abstention, and Finder ranking/feasibility remain
weak. Public rights, formal submission metadata, venue compliance, and
production deployment controls remain external. After the two human-required
submission/rights decisions and any selected venue checks are supplied, the
manuscripts can receive their final author/supervisor approval without
rewriting the evidence record.
