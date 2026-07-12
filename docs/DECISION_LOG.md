# Remediation Decision Log

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
