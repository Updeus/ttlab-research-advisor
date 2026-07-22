# Remediation Decision Log

> **Append-only historical record.** Decisions and measurements below retain
> the revision that motivated them and are not silently updated to current
> results. In particular, entries naming `corpus-04a010207327069a` or the old
> v1 metrics describe the independent-audit baseline at
> `b561fa73c1de50569d7e76261b2aa37195524c21`. Current manuscript v1-form
> evidence was executed at `73092e48f173b74f726659bd5b98224545ac23bb`
> against `corpus-f4638c633bea82b0`; current disposition is recorded under
> `docs/peer_review_readiness/`.

This append-only log records material choices made while executing
`CODEX_MASTER_REMEDIATION_PROMPT.md`. It exists so routine technical and
editorial decisions do not disappear into implementation history. Evidence and
results may refine a choice, but an earlier entry is not silently rewritten.

## 2026-07-12 baseline decisions

### D-001 — Preserve the correct repository baseline

- **Decision:** Treat `origin/main` commit
  `ce6d805afba27c2550da2ca58d1f844793ea25a8` as the code baseline. The
  remediation branch begins with the separately committed master prompt at
  `649244552f4d68fc49bcc6d35a94e99e4e638dd8`.
- **Rationale:** The earlier assessment referenced obsolete commit `713ea5c`.
- **Consequence:** All counts and claims must be regenerated; old evidence is
  historical only.

### D-002 — Use an AI-reviewed silver evaluation, not a human study

- **Decision:** Conduct no recruited-participant study. Record the evaluator as
  `codex-ai-review`, `reviewer_type=ai`, and label all resulting judgments
  AI-assisted silver labels or formative proxy review.
- **Rationale:** No participant, consent, recruitment, assessor, or ethics record
  exists. Calling Codex a human or independent assessor would be false.
- **Consequence:** The final claims characterize offline behaviour and
  source-traceability; they do not establish student usefulness, supervisor
  approval, or human usability.

### D-003 — Interpret TTLAB permission narrowly

- **Decision:** State that TTLAB explicitly authorized the project and use of
  the laboratory corpus, based on the user-provided fact.
- **Rationale:** Authorization supports undertaking the project, but no evidence
  grants REC/IRB approval, copyright ownership, or blanket redistribution rights.
- **Consequence:** Restricted PDFs, private databases, and unlicensed content are
  excluded from the sanitized release.

### D-004 — Define source-traceable independently of correctness

- **Decision:** Use *source-traceable* only for persistent paper, chunk, page,
  section, snippet, provider, timestamp, and review-state provenance.
- **Rationale:** A displayed citation or lexical overlap does not prove that an
  answer claim is entailed or factually correct.
- **Consequence:** Runtime statuses and manuscripts will not equate `grounded`
  with correctness; claim support is reported only from claim-level review.

### D-005 — Keep feature hashing as a lexical-feature baseline

- **Decision:** Rename the current 256-dimensional mode to feature hashing and
  preserve a compatibility alias for legacy clients. Add a distinct learned
  dense provider rather than relabelling existing vectors.
- **Rationale:** Hashing is reproducible and useful, but it is not a learned
  semantic embedding.
- **Consequence:** Keyword, feature-hashing, dense, and hybrid results will be
  reported separately on the same frozen corpus.

### D-006 — Make complete index manifests authoritative

- **Decision:** A versioned manifest plus checksummed vector artefact defines an
  index. SQLite embedding statuses are derived diagnostics, not the sole truth.
- **Rationale:** The 25-of-756 defect survived because file existence and stale
  statuses were treated as readiness.
- **Consequence:** Partial/demo indexes use isolated paths and cannot claim
  complete readiness; startup/evaluation fail on manifest mismatch.

### D-007 — Privacy minimization is the default

- **Decision:** Public Ask and Extension requests are transient. User profiles or
  questions may be retained only through an explicit, authenticated persistence
  path with purpose and retention metadata.
- **Rationale:** Interests, skills, constraints, and questions can be personal;
  baseline persistence was unnecessary for the public interaction.
- **Consequence:** Public history endpoints become protected and existing local
  rows are treated as legacy local-demo data.

### D-008 — Use a minimal token security boundary

- **Decision:** Implement environment-configured, hashed high-entropy bearer
  tokens mapped to stable reviewer/admin actors. Keep `local` demo mode visibly
  separate; production must fail closed without explicit secure configuration.
- **Rationale:** This supplies real authorization and attribution without
  pretending that a full institutional identity service exists.
- **Consequence:** No secret or default production credential is committed.
  Token mode uses no cookies, so CSRF is not an applicable attack path; CORS,
  HTTPS proxy, host, rate, and logging controls remain explicit.

### D-009 — Calibrate the manuscripts and remove visible placeholders

- **Decision:** Use an evidence-calibrated title, remove visible author-input
  markers, omit optional unknown metadata, and move legitimate external
  attestations to `docs/EXTERNAL_SUBMISSION_CHECKS.md`.
- **Rationale:** Red placeholders make the PDFs unfinished, while inventing
  institutional details would be worse.
- **Consequence:** The documents include the verified author identity—Jarod
  Esareesingh, Department of Computing & Information Technology, The University
  of the West Indies, `jarod.esareesingh@my.uwi.edu`, Trinidad and Tobago—and do
  not include a city.

### D-010 — Use a documented IEEE conference default

- **Decision:** Build the conference paper in US Letter with centralized
  metadata/options and target 6–8 substantive pages.
- **Rationale:** No venue-specific profile or credentials exist; US Letter is a
  defensible IEEE conference default.
- **Consequence:** Local preflight will be exhaustive, but IEEE PDF eXpress is an
  external-only submission check.

### D-011 — Release only sanitized, provenance-linked artefacts

- **Decision:** The versioned release may contain permitted code, schemas,
  redistributable seed metadata, silver labels, raw results, prompts/configs,
  figures, manifests, and hashes. It must exclude PDFs, runtime databases,
  secrets, private profile/history data, and unlicensed content.
- **Rationale:** Reproducibility does not override copyright, privacy, or access
  restrictions.
- **Consequence:** Full local-corpus reproduction may require separately
  authorized inputs and is described honestly.

## 2026-07-12 Phase 1 decisions

### D-012 — Exclude verified record/PDF mismatches from the corpus

- **Decision:** A paper is eligible for chunk indexing and evaluation only when
  its extraction is usable and its expected title is not contradicted by the
  first-page document title. Two current records are excluded:
  `vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8`
  and `pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f`.
- **Rationale:** Their downloaded PDFs are respectively “Soft-Churn: Optimal
  Switching between Prepaid Data Subscriptions on E-SIM support Smartphones”
  and “A Consumer Focused Open Data Platform”. Treating their sixteen chunks as
  source evidence would misattribute another work to the catalogue record.
- **Consequence:** The records remain visible with an explicit exclusion reason,
  but their chunks are absent from authoritative indexes, silver labels, and
  experiments until a verified permitted PDF is supplied and reprocessed.

### D-013 — Preserve uncertainty rather than force section or OCR claims

- **Decision:** Section propagation and title matching use conservative
  thresholds. Ambiguous section labels remain `Unknown`; OCR is optional and
  every page records native/OCR method, status, confidence availability, and
  warnings.
- **Rationale:** A lower unknown count is not useful if labels are fabricated,
  and OCR dependency availability is not evidence of OCR accuracy.
- **Consequence:** Section-label performance is measured on an AI-reviewed silver
  sample, while the current corpus may legitimately report zero OCR-processed
  pages.

### D-014 — Freeze the experimental corpus at 96 papers and 719 chunks

- **Decision:** Use the post-repair snapshot `corpus-04a010207327069a`, containing
  96 eligible papers and 719 eligible chunks, for retrieval and downstream
  experiments. Retain 36 no-text records as `needs_review` and exclude the two
  verified metadata/PDF mismatches and their 16 chunks.
- **Rationale:** All representations must operate on the same defensible source
  set. Catalogue visibility is not sufficient evidence for experimental
  inclusion when a PDF is absent or contradicted by its document title.
- **Consequence:** Results characterize this dated local snapshot, not all TTLAB
  publications. Any later source correction requires a new corpus hash and full
  experiment rerun.

### D-015 — Use a pinned CPU learned-dense baseline

- **Decision:** Use `sentence-transformers/all-MiniLM-L6-v2` at immutable
  revision `826711e54e001c83835913827a843d8dd0a1def9`, 384 dimensions, mean
  pooling across deterministic overlapping tokenizer windows, and final L2
  normalization. Pin PyTorch 2.13.0+cpu and the key transformer runtime.
- **Rationale:** The model is small enough for the documented CPU-only local
  workflow, has an Apache-2.0 model card, and supplies a learned representation
  that is genuinely distinct from keyword and feature-hashing baselines.
- **Consequence:** Model acquisition is an explicit networked operator action;
  ordinary search remains offline and reports a missing dense provider clearly.
  The acquired snapshot hash is recorded in the authoritative manifest.

## 2026-07-13 evaluation and documentation decisions

### D-016 — Use five evidence-linked research questions

- **Decision:** Organize the executed study around corpus/traceability,
  retrieval, RAG evidence quality, advisory/discovery outputs, and engineering
  readiness (RQ1–RQ5).
- **Rationale:** These units align with implemented work and distinct evidence
  artifacts; combining all outcomes into a single “platform effectiveness”
  question would obscure construct differences.
- **Consequence:** Every question maps to a method, source artifact, result, and
  bounded conclusion in `docs/METHODOLOGY.md`.

### D-017 — Retain negative retrieval results and the keyword reference

- **Decision:** Report all held-out modes and state that the tuned hybrid did not
  demonstrate superiority. Keep keyword as the strongest observed held-out MRR
  reference rather than selecting the more complex method by intent.
- **Rationale:** Keyword MRR was 0.9474, dense 0.9386, and tuned hybrid 0.8596;
  none of 28 family-corrected tuned-vs-baseline contrasts rejected the null.
- **Consequence:** Hybrid remains an available product mode, but neither the UI
  nor manuscripts may describe it as empirically best. The inadequate
  unanswerable false-positive behaviour is published.

### D-018 — Separate source support, citation correctness, and answer coverage

- **Decision:** Treat strict claim support (0.995), citation correctness
  (0.625), answer-point coverage (0.1358), and abstention as different
  constructs.
- **Rationale:** The offline extractive answers frequently copied supported
  source sentences that were off-topic or incomplete; all four unanswerable
  cases failed to abstain.
- **Consequence:** Runtime `grounded` remains a structural/lexical status and
  cannot be cited as factual correctness, completeness, or usefulness.

### D-019 — Treat recommendation results as a non-improvement proxy finding

- **Decision:** Report the full-Finder minus evidence-only relevance difference
  of 0.0238 with 95% CI -0.0238 to 0.0714 as no demonstrated improvement.
- **Rationale:** The confidence interval includes zero, profiles are synthetic,
  and one AI procedure applied the rubric.
- **Consequence:** The Finder's contribution is structured source/suggestion
  separation and reviewable output, not validated human advisory benefit.
  Feasibility, novelty, data access, and supervisor fit remain external.

### D-020 — Retain controlled lexical topics for public evidence

- **Decision:** Keep the controlled lexical topic system as the public author-
  topic path and use the dense prototype only as a possible review-candidate
  generator.
- **Rationale:** On the held-out split, lexical precision/recall/F1 were
  0.6522/0.4839/0.5556; dense prototype results were
  0.4175/0.6935/0.5212. The dense alternative traded substantially lower
  precision for higher recall and coverage.
- **Consequence:** Publication-derived evidence remains inspectable. Neither
  method is described as comprehensive or human-validated.

### D-021 — Preserve unreproducible historical answers as needs-reprocess

- **Decision:** Do not silently regenerate or delete 27 historical RAG answers
  whose original scope/audience/word-limit configuration is unavailable. Mark
  them `needs_reprocess`; mark 14 regenerated/verified artifacts and seven
  recommendations `ai_reviewed`.
- **Rationale:** Rewriting history with guessed configuration would destroy the
  audit trail. AI review is also not human approval.
- **Consequence:** Forty-eight attributed events and their hash chain preserve
  the decision; public guidance must not present `needs_reprocess` records as
  reviewed answers.

### D-022 — Make performance and full reproduction fail-closed evidence gates

- **Decision:** Do not report a benchmark or scalability result until
  `performance_full_results.json` exists with full profile, hardware, raw
  repetitions, aggregates, failures, corpus, commit, and clean/dirty state. Do
  not claim full reproduction without its final manifest/logs.
- **Rationale:** A harness, quick run, or historical intent does not prove a
  full-corpus execution.
- **Consequence:** Phase 7 documentation explicitly records both gates as
  pending at its snapshot. Later execution must update status rather than
  backfill numbers manually.

### D-023 — Make executed documentation canonical

- **Decision:** Add `docs/METHODOLOGY.md`,
  `docs/EVALUATION_PROTOCOL.md`,
  `docs/DATA_AND_ARTIFACT_AVAILABILITY.md`, and
  `docs/REPRODUCIBILITY.md` as canonical research records. Retain older sample
  evaluation files and compatibility documentation only as scaffolds/pointers.
- **Rationale:** The earlier README/status/evaluation prose still described
  proposed gold labels, no authentication, no OCR, a partial index, and
  unexecuted metrics after those states had changed.
- **Consequence:** Public documentation now distinguishes current evidence,
  legacy scaffolds, pending gates, and external-only attestations. No completed
  result depends on filling old blank human-review templates.

### D-024 — Rebuild the release only from the final clean commit

- **Decision:** Treat the local archive for commit `d0d84aa6101a...` as a
  provisional builder proof, not the final release.
- **Rationale:** Its source commit predates the retrieval, generated-review, and
  manuscript-evidence commits.
- **Consequence:** Final delivery must rebuild, scan, checksum, and verify a new
  bundle from the final commit, then record or create the prepared tag without
  changing repository visibility.

### D-025 — Reject benchmark evidence when a read path changes the corpus file

- **Decision:** Replace the FTS5 capability probe's temporary table
  creation/deletion with SQLite's read-only compile-option query, retain the
  failed 17-stage run only as ignored diagnostic evidence, and restart the full
  profile from an integrity-checked standalone database snapshot.
- **Rationale:** The former probe changed the SQLite schema cookie and physical
  file hash during keyword retrieval even though row counts were unchanged.
  Treating that as harmless would defeat the benchmark's source-boundary gate.
- **Consequence:** A regression test and a real six-query probe now require an
  unchanged database SHA-256. Only a newly sealed run may support performance
  claims.

### D-026 — Use the programme description without inventing a degree formula

- **Decision:** Use the user-supported descriptor `MSc Data Science Project`
  but omit a formal “submitted for the degree of” formula.
- **Rationale:** The project context is author-provided, whereas no approved
  university template or official degree nomenclature was supplied.
- **Consequence:** The thesis title page remains informative without claiming
  an unverified institutional submission formula; any required official
  wording remains in the external submission checklist.

### D-027 — Narrow accessibility and external-format conclusions to executed evidence

- **Decision:** State that automated accessibility regression checks passed
  without claiming WCAG conformance or assistive-technology usability. Describe
  the external check as three CC BY JATS/XML records mapped into the production
  chunker contract, not as validation of the main PDF-ingestion pipeline or
  cross-domain retrieval quality.
- **Rationale:** Automated axe, keyboard, viewport, and Chromium checks do not
  replace human assistive-technology assessment. The external harness has a
  dedicated JATS parser before the shared chunker.
- **Consequence:** RQ5 remains answerable as a bounded engineering-readiness
  question while its conclusions preserve the actual test boundary.

### D-028 — Make final document and route inspection reproducible

- **Decision:** Add fail-loud manuscript checks for temporary performance text
  and correctly parsed font embedding, validate repository-local documentation
  links, and capture every primary live route at desktop and mobile widths with
  image hashes and overflow/error status.
- **Rationale:** Source compilation and mocked tests alone cannot establish that
  final PDFs and live routes are readable or free of visible stale state.
- **Consequence:** Final closure requires both automated gates and visual
  inspection. The PDFs remain untagged under the available toolchain, so no PDF
  accessibility-conformance claim follows.

### D-029 — Exclude binary interface screenshots from the sanitized release

- **Decision:** Exclude the complete tracked interface-screenshot directory
  from the sanitized reproducibility archive while retaining code-native figure
  sources and sanitized numeric evidence.
- **Rationale:** Screenshots can render verbatim paper passages, generated
  answers, or contact data. The JSON field sanitizer cannot reliably inspect or
  redact text embedded in a raster image.
- **Consequence:** Manuscript screenshots remain subject to the separate
  Git/manuscript distribution review, and the sanitized archive does not claim
  to be a standalone manuscript-build bundle. A release regression test checks
  that no screenshot-directory member enters the archive.
