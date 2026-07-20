# Independent peer-review readiness audit

Audit characterization: **AI-assisted independent audit; not human peer review**.

Repository candidate audited: main at
b561fa73c1de50569d7e76261b2aa37195524c21.

## 1. Executive assessment

The TTLAB Research Intelligence Platform is a substantial, buildable research
artifact with unusually candid negative-result reporting. Backend, frontend,
E2E, document, dependency, and release-component checks are broad and largely
pass. The corpus/index boundary is much stronger than a typical demonstration:
96 technically eligible papers produce 719 chunks represented one-for-one in
keyword, feature-hashing, and pinned learned-dense indexes.

It is **not ready as a formal supervisor-review candidate or external
peer-review submission**. It is ready only for a remediation-focused supervisor
review using these audit artifacts.

The reason is not a lack of code volume or green tests. The hard manuscript
constraints fail; clean current-candidate reproduction fails; public
editorial approval is absent; runtime grounded status does not verify claims;
Ask does not abstain; the flagship Finder largely echoes profile constraints and
generic templates; and its evaluation establishes neither relevance improvement
nor feasibility. These are central validity and product-contract failures.

Issue register:

| Severity | Open issues |
|---|---:|
| BLOCKER | 6 |
| CRITICAL | 8 |
| HIGH | 28 |
| MEDIUM | 24 |
| LOW | 1 |
| **Total** | **67** |

| Fixability | Open issues |
|---|---:|
| AUTO | 9 |
| AUTO_CONSERVATIVE | 44 |
| AUTO_EXPERIMENT | 9 |
| HUMAN_REQUIRED | 2 |
| ENVIRONMENT_REQUIRED | 3 |
| **Total** | **67** |

The complete, machine-readable register is REMEDIATION_MATRIX.csv.

Register semantics apply to every row: severity is the peer-review impact class;
the summary states the failure mode; and the evidence cell is the exact
reproduction or inspection anchor. AUTO, AUTO_CONSERVATIVE, and AUTO_EXPERIMENT
rows are **confirmed in the current checkout** by execution, database/artifact
inspection, rendered-output inspection, or source-contract inspection as stated.
HUMAN_REQUIRED rows are **repository-confirmed external evidence absent**;
ENVIRONMENT_REQUIRED rows are **statically confirmed, deployment reproduction
pending**. The verification cell defines the closure test, not evidence that the
open issue is already fixed.

### Five most serious technical/scientific obstacles

1. **PAPER-001:** the IEEE paper is 8 pages with 29 cited references, not at
   most 6 pages including references with approximately 20.
2. **THESIS-001/THESIS-002:** the thesis is 74 pages and the literature/research
   design is too thin to solve the requirement by simple formatting.
3. **REPRO-001/REPRO-003:** a clean exact-HEAD full reproduction fails at the
   performance stage with 40 index-status failures, so no current final manifest,
   checksums, manuscript build, or release is produced.
4. **RAG-001/RAG-002:** out-of-corpus questions can receive grounded answers
   because generation has no answerability gate and grounding is aggregate
   lexical/structural validation, not claim entailment.
5. **FINDER-001/FINDER-002:** the central Thesis Extension Finder's feasibility
   fields are circular or generic; uplift is uncertain and all 84 evaluated
   feasibility judgments are partial.

## 2. Submission blockers

### PAPER-001 — hard paper limit

The compiled paper is 8 Letter pages. Its BBL contains 29 references. Page 8 is
only references [19]-[29] in the left column, with the right column blank. The
current validator accepts 6-8 pages, so its PASS contradicts the required
maximum.

The safe compression path is specific:

1. remove the duplicated Evaluation Dashboard screenshot;
2. replace the 12-row performance table with two bounded sentences;
3. remove the capability-comparison table and retain concise prose;
4. retain one unified workflow figure rather than two architecture/workflow
   figures;
5. remove the standard recall equation/tutorial, not design-critical details;
6. collapse repeated Discussion/Threats prose;
7. reduce paper-only citations from 29 to about 20 while retaining the thesis
   bibliography.

This should save 2.1-2.75 pages without margin, font, or readability abuse. Do
not remove the negative hybrid, citation, coverage, abstention, feasibility, or
same-AI evidence boundaries.

### THESIS-001 — hard thesis limit and substantive depth

The thesis is 74 A4 pages: 10 front matter, 48 main chapters, 11 appendices, and
5 bibliography pages. The literature review is approximately three pages. The
correct repair is substantive expansion of literature synthesis, design-science
method mapping, experiment provenance, and Finder/frontend analysis, paired with
less repetition in Results/Discussion/Conclusion.

### REPRO-001 — current-candidate completion evidence

At baseline:

- current HEAD was b561fa7;
- thesis generated evidence named f4abb767;
- performance evidence named 5ccf22e;
- tracked index manifests named 166c6fc;
- Phase 1 and QA execution records included dirty worktrees;
- the existing root release was for d0d84aa;
- no top-level exact-current reproduction_manifest.json and
  REPRODUCTION_SHA256SUMS were retained.

Yet the paper states that clean-commit full reproduction passed, and the thesis
traceability appendix cites a reproduction manifest as RQ5 evidence. Script
availability and component artifacts do not close that claim.

### REPRO-003 — exact-current reproduction pipeline failure

The audit ran the documented full reproduction in a clean detached copy of
b561fa7. It failed at `performance-full`: 40 samples failed because both
authoritative vector manifests covered 719 eligible chunks while every one of the
735 database chunk rows remained `not_indexed`. The reproducer creates both
indexes with `--no-status-update` at `scripts/reproduce_all.sh:153-156`, then
starts probes whose integrity gate requires those statuses to agree. No external
service or credential was involved. The final validator, manuscript rebuild,
manifest/checksum inventory, and release stages therefore never ran.

### PUBLIC-001 — no editorial public boundary

Every current paper and topic record is needs_review, yet anonymous endpoints
return catalogue records and technically eligible content. Corpus eligibility
answers whether text may enter an experimental index; it does not answer whether
metadata, identity, topic, summary, or recommendation has been approved as a
public fact.

A fail-closed approval gate is AI-fixable. Actual approval/identity decisions
require accountable reviewers.

### RIGHTS-001 and SUBMISSION-001 — legitimate human closure

TTLAB authorization is an explicit project fact and must remain so. It is not
ethics approval, a human-participant study, or blanket third-party redistribution
permission. Per-paper public-use rights, institutional controller procedures,
formal thesis fields, official TTLAB name, title/author approval, target venue,
funding/COI, and PDF Checker credentials remain external decisions. They are
narrowly specified in HUMAN_REQUIRED_ITEMS.md.

## 3. Software findings

### Strong controls confirmed

- 255 backend tests passed.
- 20 frontend unit tests and 6 Chromium E2E tests passed.
- Frontend production build passed.
- npm high-severity audit reported no vulnerabilities.
- Public Ask/Finder requests are non-persistent and profile/question state
  remains in browser/request memory by default.
- No unsafe HTML rendering was found.
- Public full-chunk access is restricted.
- Release scanning excludes PDFs, SQLite, indexes, raw/full extraction, secrets,
  model caches, private prompts, and screenshots.
- Index manifests detect many stale/count/hash/configuration mismatches.

### Architecture and state defects

The new scheduled worker can overwrite reviewed metadata, reuse a stale local PDF
and cached extraction, and leave partially promoted generations because seed,
database, files, chunks, topics, and indexes are mutated through separate commits
and file writes (SYNC-001 through SYNC-003). Index payload/manifest publication
also has a validation/use race (INDEX-001). Extraction and chunk caches are not
fully atomic/content-bound (ARTIFACT-001).

SQLite foreign-key enforcement is off and malformed JSON is silently reduced to
an empty list (DB-001). The runtime scheduler writes a tracked seed by default
(SYNC-004). These are reproducibility/integrity issues even though current
quick-check and foreign-key-check outputs report no existing violations.

### Configuration and provider defects

Provider diagnostics call Ollama the default while auto resolves to offline
extraction unless configured (API-001). Public clients can request arbitrary
installed Ollama tags without immutable digest/prompt provenance (LLM-001). The
optional OpenAI adapter is a placeholder that can produce a non-answer labeled
as OpenAI if enabled (LLM-002). Feature hashing remains accessible through a
semantic alias despite the manuscripts correctly saying it is lexical
(INDEX-002).

## 4. Retrieval and RAG findings

### Retrieval implementation

The frozen eligible indexes are complete and deterministic for the observed
rebuild. A fresh dense rebuild had the same ordered record hash as the tracked
payload despite timestamp/build-ID differences. The manuscript correctly reports
that keyword has the strongest point estimates and that neither heuristic nor
tuned hybrid establishes superiority.

The product nevertheless defaults Search, Ask, and Finder to heuristic hybrid
(RAG-003). This is inconsistent with its own held-out evidence. A conservative
keyword default is warranted until task-specific development evidence establishes
another choice.

### Grounding and abstention

rag_answerer.py generates whenever retrieval returns any chunk. It then attaches
the top retrieved chunks as citations. citation_verifier.py checks required
fields and whether answer vocabulary overlaps the union of cited snippets by at
least 0.08. It does not decompose claims, verify inline source IDs, or test
entailment for each claim.

This is why an answer can be labeled grounded while its citations are irrelevant.
The repository's own AI-assisted evaluation confirms the consequence:

- 398/400 claims fully supported, 2 partial, 0 unsupported;
- citation correctness 0.625;
- answer-point coverage 0.135802;
- returned-citation utilization 0.592;
- 0/4 unanswerable QA cases abstained.

High claim support here mostly reflects extractive copying. It is not end-to-end
answer correctness. RAG-001, RAG-002, and QA-001 require new claim/answerability
logic and versioned experiments, not relabeling the current results.

### Evaluation leakage and uncertainty

The same declared AI procedure created and re-inspected silver labels. Descriptive
ablations repeatedly inspect the held-out test set. The code labels that use
descriptive, which is honest, but the set is no longer a future tuning lockbox.
Confidence intervals resample cases, not silver-label uncertainty. Freeze this
set historically and use a fresh preregistered confirmatory set if stronger
claims are pursued (EVAL-002).

## 5. Thesis Extension Finder findings

The Finder successfully separates source facts, gap status, and system
suggestion in its schema and avoids claiming supervisor endorsement. That is a
real design strength.

Its feasibility logic does not validate feasibility:

- implementation time is derived from requested time/preferred difficulty;
- timeline scoring receives profile preference rather than independent project
  complexity;
- data availability can be forced by the student's constraint phrase;
- MVPs and evaluation plans are project-type templates;
- risk and required-skill review checks internal consistency with the same
  heuristics;
- the verifier confirms citation structure, not practical feasibility.

The evaluation result is appropriately negative: full-minus-evidence-only
relevance is 0.0238 with 95 percent CI [-0.024, 0.071], and all 84 full-finder
feasibility judgments are partial. The platform is an auditable recommendation
prototype, not a validated academic advisor. The UI can also retain evidence-only
and advisor outputs from different profiles simultaneously (UI-005).

## 6. Frontend findings

All principal routes were inspected. The most material defects are:

- review actions are not filtered by actor/reviewer type and fail in the default
  demo service role (REVIEW-001);
- correction, approval, and public effective content are disconnected
  (REVIEW-002);
- mutation success leaves stale central/selected state (UI-001);
- review/event/author collections silently truncate (UI-002);
- catalogue versus searchable/public boundaries are mislabeled (UI-003);
- overlapping/editable request state can show evidence under the wrong query or
  route (UI-004);
- artifact refresh can be a no-op presented as success (UI-006);
- invalid year input can clear a valid year (UI-007);
- paper-list failure blocks independent routes (UI-008);
- reviewers cannot inspect all recommendation fields or perform the implemented
  extraction-review workflow (UI-009);
- reviewer bearer token is sent with public calls (UI-010);
- Paper Browser lacks required facets (UI-011).

Automated axe coverage includes only three simple states. Complex Finder,
Evaluation, details, error states, and authenticated review are absent; Explorer
also lacks programmatic current-route state (A11Y-001). Passing automated checks
therefore does not establish WCAG or assistive-technology usability.

## 7. Data, governance, security, and deployment findings

Data quality remains visibly incomplete:

- 36 records lack eligible text;
- two PDFs are suspected title/content mismatches;
- 199 eligible chunks have Unknown section;
- no frozen-corpus paper exercised OCR;
- the identity audit retains unreviewed/malformed author records;
- every topic remains needs_review.

These facts are mostly disclosed, which is good. The public API does not enforce
the editorial boundary those facts require.

Security controls are reasonable for a local MVP: explicit hosts/origins,
mutation authentication, request/download/page limits, redacted logging, path
validation, rate controls, and release exclusions. Residual production work is
real and accurately documented: DNS rebinding is not prevented at the network
layer; PyMuPDF parses untrusted files in process; rate limits are per-process;
SQLite uses rollback journal with no explicit multi-process contention policy.
These are ENVIRONMENT_REQUIRED, not reasons to demand production-scale
infrastructure from a bounded manuscript. They do prevent a public-production
claim.

## 8. Thesis findings

### Academic strengths

- Aim, artifact scope, source-traceability definition, and no-human boundary are
  clear.
- Numerical result claims mostly reconcile with generated macros and raw files.
- Negative retrieval, QA, Finder, topic, identity, and external-validity results
  are retained.
- Ethics text correctly separates corpus authorization, research ethics, and
  copyright.
- Appendices include useful schema/API/reproduction/review instruments.

### Academic weaknesses

1. The 74-page build misses the hard threshold (THESIS-001).
2. The literature review is too short and the design-science label lacks an
   established framework/mapping (THESIS-002).
3. The title is generic and emphasizes AI summarization/idea generation over the
   evaluated research-intelligence contribution (THESIS-003).
4. Public-interface and central Finder design receive little depth and no
   readable Finder/Admin evidence figure (THESIS-004).
5. Aggregate metrics obscure sparse class support and AI-label uncertainty
   (THESIS-005).
6. RQ4/RQ5 are catch-all questions (THESIS-006).
7. Repeated metric prose consumes space that should support literature and
   methodology (THESIS-007).
8. Both PDFs are untagged; screenshots are too dense at print scale and an
   internal corpus hash appears on the formal thesis title page (PDFDOC-001).
9. The build ignores repeated intermediate BibTeX errors (LATEX-001).

The thesis is suitable as a strong remediation draft, not as a final formal
submission.

## 9. IEEE paper findings

The paper is scientifically honest about its negative results and generally
well structured. Its current form cannot be submitted:

- 8 pages and 29 references violate the hard constraint;
- five RQs overload limited space;
- full-width capability table, two figures, dashboard screenshot, 12-row
  performance table, metric tutorial, and repeated limitations consume the two
  pages that must be recovered;
- exact-current reproduction is overstated;
- current generic IEEE Xplore guidance says compliant PDFs contain no bookmarks
  or links, while qpdf shows outlines, open action, annotations, URI and GoTo
  entries in this build
  ([IEEE Author Center](https://conferences.ieeeauthorcenter.ieee.org/write-your-paper/meet-ieee-xplore-requirements/));
- Hal Daumé III is rendered incorrectly as H. D. III;
- the QA paragraph omits the two partially supported claims and case-only
  uncertainty boundary;
- target venue/anonymity/copyright/page-size profile remains a human decision.

The exact compression order is encoded in AUTO_FIX_PLAN.md. Removing negative
results to reach six pages is explicitly prohibited.

## 10. Reproducibility findings

The project has strong component provenance: raw rankings, review labels, config
hashes, model revision, corpus snapshot, source hashes, validators, deterministic
index records, release scans, and one-command scripts.

The scientific execution history is fragmented:

- Phase 1 ran with a materially dirty tree;
- QA run manifests say working_tree_dirty=true;
- generated manuscripts bind an older clean application base while using exact
  live generator hashes;
- performance is clean but older;
- scheduled ingestion is newer than manuscript evidence;
- the baseline exact-current manifest and release were absent.

File hashes make dirty-run evidence more auditable, but cannot reconstruct every
untracked dependency. A clean current rerun is the correct closure step.

The full reproduction script also runs its named PDF identity audit before
run-local extraction exists, producing 98 not_assessed records. Later overwrite
extraction independently restores the correct 96 matched / 2 mismatch / 36
no-PDF partition, so the final exclusions are not inherited; the early audit log
is simply non-evidence (REPRO-002).

The clean exact-HEAD run failed after approximately 32 minutes at
`performance-full`. The benchmark recorded all 17 stage names but 40 failed
samples: six each for feature-hashing, dense, hybrid, answer, recommendation, and
ASGI probes, and four frontend page-load probes. The common failure was an index
integrity exception for 719 database/manifest status disagreements. The run-local
database confirmed 735 `not_indexed` rows. This is a repository defect caused by
the reproduction script's two `--no-status-update` builds, not an environmental
failure (REPRO-003).

## 11. Cross-document contradictions

The detailed table is in CROSS_DOCUMENT_CONSISTENCY.md. The material
contradictions are:

1. current HEAD versus older manuscript/evaluation/index revisions;
2. hybrid product defaults versus keyword's strongest held-out evidence;
3. runtime grounded badge versus documented structural-only meaning;
4. technically eligible/public presentation versus universal needs_review
   editorial state;
5. dashboard current labeling versus file-existence/mtime selection;
6. stale documented test counts versus live counts;
7. paper/thesis validator PASS versus hard 6/75 requirements;
8. completed-reproduction prose versus a clean exact-current run that fails
   before final evidence/release generation;
9. paper's approximate-20 reference goal versus 29 cited entries;
10. provider diagnostics saying Ollama versus actual offline-extractive auto
    default.

Different raw SQLite hashes are not automatically contradictions: source-stage
changes and canonical SQLite backup representation can legitimately differ.
The corpus snapshot ID/hash and ordered chunk/source hashes are the meaningful
scientific identity and should be stated alongside file hashes.

## 12. Prioritized remediation sequence

1. **Correct gates and make clean reproduction internally consistent** —
   VALIDATE-001, REPRO-001/002/003, PROVENANCE-001.
2. **Fail closed on public/editorial state** — PUBLIC-001, CORPUS-001,
   rights-matrix skeleton and catalogue/index distinction.
3. **Make ingestion/derived state generational** — SYNC-001/002/003,
   INDEX-001, ARTIFACT-001, DB-001.
4. **Repair RAG answerability and claim grounding** — RAG-001/002/003, QA-001.
5. **Repair Finder feasibility and rerun a versioned baseline comparison** —
   FINDER-001/002.
6. **Complete review and frontend contracts** — REVIEW-001/002 and UI issues.
7. **Bind evaluation/dashboard artifacts to full provenance** — EVAL-001/002.
8. **Expand/rebalance the thesis** — reach substantive 75+ pages.
9. **Compress/preflight the paper** — at most six readable pages and about 20
   references.
10. **Run and retain exact candidate closure**, then obtain only the genuinely
    human/institutional approvals listed separately.

AUTO_FIX_PLAN.md supplies phase dependencies, commands, and likely commits.

## 13. Peer-review risk assessment

| Risk | Current level | Why |
|---|---|---|
| Immediate desk rejection / format failure | **certain if submitted now** | paper 8 pages; thesis below stated threshold; venue profile unresolved |
| Reproducibility challenge | **critical** | evidence spans revisions; clean exact-current reproduction fails on 719 database/index status disagreements before final manifest/release generation |
| RAG validity criticism | **critical** | no answerability gate; structural overlap called grounded; poor citation/coverage/abstention |
| Recommendation/advisor validity criticism | **critical** | circular feasibility, generic plans, uncertain uplift, no human feasibility |
| Data/editorial criticism | **high** | public records/topics unapproved; identity and corpus gaps remain |
| Methodology criticism | **high** | same-AI silver, small/sparse lockbox, repeated test inspection, thin design-science grounding |
| Frontend/review criticism | **high** | review transitions/effective corrections incomplete; stale/truncated/misbound states |
| Security/deployment criticism | **medium to high if public deployment is claimed** | local controls are good; network/process/concurrency operations are not deployed |
| Ethics/copyright criticism | **controlled in prose, unresolved operationally** | wording is cautious; human rights/controller decisions still needed |
| Risk of hiding negative evidence during compression | **high unless explicitly guarded** | two pages must be removed; plan identifies non-negotiable negative results |

### Final audit opinion

The work has a credible path to peer-review readiness. The repository's strongest
asset is not the current QA or recommendation quality; it is the disciplined
evidence boundary and willingness to report failure. Readiness depends on
bringing runtime labels and public behavior up to that same standard, freezing
one exact evaluated revision, and meeting the manuscript constraints without
weakening the negative record.
