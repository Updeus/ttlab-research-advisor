# Dependency-aware AI remediation plan

This plan is the handoff for a remediation run. It covers AUTO,
AUTO_CONSERVATIVE, and AUTO_EXPERIMENT rows in REMEDIATION_MATRIX.csv. It does
not authorize invention of human evidence, approvals, scores, rights, or venue
requirements. Preserve the existing negative findings and raw artifacts.

## Operating rules for the remediation run

1. Start from the audit commit and a clean branch.
2. Treat the current checkout and retained raw artifacts as the source of truth.
3. Make small commits in the order below; do not combine manuscript compression
   with core RAG or data-state changes.
4. Never replace old negative metrics in place. Version new datasets/runs and
   show old-versus-new results.
5. Do not call AI-created labels human review.
6. Do not make technically eligible content public until a separate approval
   gate permits it.
7. Run the relevant targeted tests after each commit and the complete gates at
   the end.

## Phase 0 — Correct the acceptance gates and freeze the study boundary

Issues: VALIDATE-001, REPRO-001, REPRO-002, REPRO-003, PROVENANCE-001, PAPER-004,
DOC-001, SYNC-004.

Work:

1. Change manuscript preflight to enforce paper pages <= 6 and thesis pages >=
   75, with boundary tests.
2. Make the PDF title audit run after fresh extraction; clear run-local derived
   state first and assert the final 96/2/36 partition and 719 eligible chunks.
3. Stop building authoritative indexes with an intentionally stale database
   status. Update both provider statuses transactionally (or perform one explicit
   synchronized promotion), then validate manifests and status before any probe.
4. Add a regression that starts with 735 `not_indexed` rows and proves a full
   build promotes the 719 eligible rows consistently for both providers.
5. Move scheduled discovery output away from the tracked seed; add an explicit
   reviewed-seed export.
6. Add one evaluated commit/tree/dirty-state boundary to every paper/thesis
   evidence manifest.
7. Decide in code, not by implication, whether current HEAD or a tagged earlier
   artifact is the study candidate. The manuscripts must name that revision.
8. Remove brittle hand-maintained test counts or generate them from the final
   gate.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_reproduction_manifest.py \
  backend/tests/test_pdf_parser.py \
  backend/tests/test_metadata_cleaner.py \
  backend/tests/test_index_manifest.py
.venv/bin/python scripts/validate_manuscripts.py
git status --short
~~~

The current manuscript validation should deliberately fail until the paper and
thesis are repaired.

Likely commits:

1. Enforce manuscript submission constraints
2. Make full reproduction identity audit run-bound
3. Synchronize authoritative index and database status
4. Separate runtime discovery from frozen seed data
5. Bind manuscript evidence to the evaluated revision

## Phase 1 — Establish a fail-closed public/editorial boundary

Issues: PUBLIC-001, CORPUS-001, META-001, PDF-001, TOPIC-001, UI-003.

Work:

1. Add publication approval independently of extraction/index eligibility.
2. Make anonymous paper/topic/author/artifact routes fail closed.
3. Remove the legacy eligibility fallback from runtime code and keep any legacy
   conversion in an audited migration.
4. Represent unapproved, unresolved, excluded, no-text, and rights-restricted
   states explicitly in API schemas.
5. Conservatively normalize obvious parser artifacts while preserving original
   source strings and aliases; never auto-merge ambiguous identities.
6. Add a machine-readable rights/public-use matrix schema with all entries
   defaulting to denied/pending. Human decisions can be supplied later.
7. Make the browser and Ask scopes distinguish catalogue records from indexed
   and approved public records.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_api.py \
  backend/tests/test_keyword_read_only.py \
  backend/tests/test_topic_explorer.py \
  backend/tests/test_topic_author_eval.py
npm --prefix frontend test
~~~

Add negative tests proving that eligible-but-unapproved rows, mismatched PDFs,
and needs-review topics cannot appear anonymously.

Likely commits:

1. Add fail-closed public publication state
2. Preserve metadata identity provenance
3. Expose catalogue and searchable corpus boundaries

## Phase 2 — Make ingestion and derived state generational

Issues: SYNC-001, SYNC-002, SYNC-003, INDEX-001, ARTIFACT-001, DB-001,
OCR-001.

Work:

1. Introduce immutable staged generations for database-derived files and one
   atomic active-generation pointer.
2. Record PDF SHA-256, resolved URL, extractor/chunker versions/configuration,
   text hash, and parent generation.
3. Invalidate extraction, chunks, topics and all indexes on a material parent
   change.
4. Publish index payload/manifest within one immutable generation and validate
   the bytes that are actually consumed.
5. Use temp-file, fsync and atomic rename for extraction/chunk artifacts.
6. Enable SQLite foreign keys on every connection, audit current rows, and
   quarantine malformed JSON instead of mapping it to an empty value.
7. Pin OCR language/config/locale/render settings and add a small scanned fixture.
8. Protect reviewed fields from scheduled source updates; record conflicts.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_ingestion_sync.py \
  backend/tests/test_pdf_downloader.py \
  backend/tests/test_pdf_parser.py \
  backend/tests/test_chunker.py \
  backend/tests/test_index_manifest.py \
  backend/tests/test_database_snapshot.py
~~~

Required new tests:

- fault injection after every sync stage;
- concurrent index reader/writer;
- replacement of a PDF under the same paper ID;
- rejected orphan inserts;
- malformed JSON quarantine;
- deterministic OCR fixture.

Likely commits:

1. Version PDF extraction and chunk dependencies
2. Promote ingestion generations atomically
3. Publish immutable index generations
4. Enforce SQLite and JSON integrity

## Phase 3 — Repair Ask TTLAB answerability and claim grounding

Issues: RAG-001, RAG-002, RAG-003, QA-001, INDEX-002, API-001, LLM-001,
LLM-002.

Work:

1. Separate retrieval availability, answerability, structural citation validity,
   claim support, and final grounding into distinct fields.
2. Add conservative answerability thresholds using development hard negatives;
   abstain when support is insufficient.
3. Require structured atomic claims with exact source IDs and omit unused
   citations.
4. Add a claim-source verifier and calibrate it on development data. Preserve
   partial/unsupported claims rather than hiding them.
5. Make keyword the conservative product default unless a task-specific
   development experiment justifies another mode.
6. Remove feature-hashing semantic aliases from the canonical API.
7. Return requested/configured/effective/fallback provider separately.
8. Allowlist immutable local-model digests and retain prompt-template hash and
   generation parameters.
9. Remove the OpenAI stub from supported providers or implement the full
   contract.
10. Version a new QA evaluation; keep the existing 0.625/0.136/0-abstention run
    as the historical baseline.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_ask.py \
  backend/tests/test_qa_faithfulness_evaluation.py \
  backend/tests/test_retrieval.py \
  backend/tests/test_retrieval_experiment.py
~~~

New adversarial tests must include medical, fantastical, and out-of-corpus
questions. Report answerable/unanswerable precision, recall, false-positive rate,
calibration, citation correctness/completeness/utilization, and answer-point
coverage.

Likely commits:

1. Separate structural and claim grounding states
2. Add conservative Ask TTLAB abstention
3. Pin effective generation provenance
4. Re-evaluate source-cited question answering

## Phase 4 — Repair the Thesis Extension Finder

Issues: FINDER-001, FINDER-002, UI-005.

Work:

1. Make paper facts, paper-stated future work, inferred gap, system suggestion,
   assumptions, unknowns, and external confirmations distinct schema fields.
2. Derive time/data/difficulty/risk from candidate-specific evidence and explicit
   constraint rules instead of echoing the requested profile.
3. Produce candidate-specific MVP and evaluation plans. Do not suggest human
   studies without an ethics/approval warning.
4. Add explicit unknown/needs-supervisor values rather than manufacturing
   feasibility.
5. Replace parallel frontend result states with one submitted-profile/result
   record.
6. Re-run source-derived AI-assisted evaluation against the evidence-only
   baseline on a fresh locked dataset. Do not present it as human feasibility.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_extension_recommender.py \
  backend/tests/test_admin_evaluation.py
npm --prefix frontend test -- --run
~~~

Add counterfactual profile tests, constraint violations, candidate-specific
content tests, rank sensitivity, and exact source-field verification.

Likely commits:

1. Make Finder feasibility evidence explicit
2. Generate candidate-specific Finder plans
3. Bind Finder UI to one submitted profile
4. Version the Finder baseline comparison

## Phase 5 — Complete and correct admin review

Issues: REVIEW-001, REVIEW-002, UI-001, UI-002, UI-006, UI-007, UI-009.

Work:

1. Add an actor-capabilities endpoint and render only allowed transitions.
2. Separate correction save from decision/approval.
3. Define an immutable artifact version/effective-approved-payload contract.
4. Make public detail render only the effective approved payload and its exact
   provenance.
5. Refresh central paper and selected-item state from mutation responses.
6. Add pagination/total indicators for queue, events, and authors.
7. Implement complete recommendation preview/editing and extraction
   diagnostics/reprocess UI.
8. Validate year and all metadata fields before sending; show structured backend
   errors.
9. Make refresh create a new version or explicitly report unchanged.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest \
  backend/tests/test_admin_evaluation.py \
  backend/tests/test_paper_artifacts.py \
  backend/tests/test_security_privacy.py
npm --prefix frontend test
npm --prefix frontend run test:e2e
~~~

Required E2E matrix: human reviewer, human admin, AI reviewer, demo service,
anonymous detail after correction/approval, extraction failure, and collections
beyond every pagination limit.

Likely commits:

1. Expose review actor capabilities
2. Publish only effective approved artifacts
3. Complete review and extraction workflows
4. Paginate review and explorer collections

## Phase 6 — Frontend integrity, resilience, and accessibility

Issues: UI-004, UI-008, UI-010, UI-011, A11Y-001.

Work:

1. Store immutable submitted request beside each response.
2. Use one form submit path and request sequencing/AbortController.
3. Make route state the Explorer source of truth.
4. Keep the shell usable when the paper list fails; use route-level boundaries.
5. Split public and privileged API clients so tokens are sent only when needed.
6. Add year/author/topic/venue facets with non-sensitive URL state.
7. Add aria-current, keyboard tests, focus restoration, live-region behavior, and
   axe coverage for all principal loaded/generated/error/authenticated states.

Verification:

~~~bash
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend audit --audit-level=high
~~~

Likely commits:

1. Bind frontend results to submitted requests
2. Keep routes usable under partial API failure
3. Minimize reviewer credential exposure
4. Expand accessible route and facet coverage

## Phase 7 — Rebuild evaluation and evidence truth surfaces

Issues: EVAL-001, EVAL-002, THESIS-005, TOPIC-001, TEST-001.

Work:

1. Create a common evaluation manifest contract binding commit/tree, corpus,
   dataset, config, model, generator, created time, and reviewer type.
2. Make the dashboard report current, frozen, stale, unavailable, and invalid
   separately.
3. Freeze the existing retrieval test as historical after repeated descriptive
   ablations; use development/analysis partitions for further tuning.
4. Add per-class support/confusion, not-estimable cells, and explicit
   label-uncertainty limits to section/topic/retrieval reporting.
5. Upgrade or explicitly time-bound dependency deprecation suppressions and
   document the torch advisory source.

Verification:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
make docs-validate
~~~

Changing any evidence dependency without rerunning must turn the dashboard stale.

Likely commits:

1. Bind evaluation results to their full provenance
2. Expose stale and invalid evidence states
3. Report sparse support and label uncertainty
4. Refresh dependency verification

## Phase 8 — Expand and rebalance the thesis

Issues: THESIS-001, THESIS-002, THESIS-003, THESIS-004, THESIS-005,
THESIS-006, THESIS-007, PDFDOC-001, LATEX-001, LATEX-002.

Work:

1. Add a cited design-science framework and operational mapping.
2. Expand literature synthesis on IR judgments, citation attribution,
   answerability, human-centered recommenders, educational project advice,
   governance, and failure analysis.
3. Add requirements-to-route/evidence/degraded-state/test traceability and
   readable Finder/Admin figures.
4. Add per-class denominators and uncertainty scope.
5. Split or subordinate catch-all RQs.
6. Remove repeated metric prose from Discussion/Conclusion and use the recovered
   space for synthesis.
7. Adopt the evidence-calibrated title after human approval.
8. Move internal corpus hash from the title page; improve screenshot/heading
   legibility; preserve the untagged-PDF limitation unless tagging is delivered.
9. Stop normalizing intermediate BibTeX errors.

Verification:

~~~bash
make thesis-assets-frozen
make thesis-compile
.venv/bin/python scripts/validate_manuscripts.py
qpdf --check build/thesis.pdf
pdffonts build/thesis.pdf
pdfinfo build/thesis.pdf
~~~

The PDF must be at least 75 genuinely substantive pages. Render and inspect every
page.

Likely commits:

1. Strengthen thesis research design and literature
2. Document Finder and review interface evidence
3. Rebalance thesis results discussion and traceability
4. Polish and validate the thesis submission build

## Phase 9 — Compress and preflight the IEEE paper

Issues: PAPER-001, PAPER-002, PAPER-003, PAPER-005, BIB-001, LATEX-002.

Compression sequence:

1. Remove the duplicated Evaluation Dashboard screenshot.
2. Replace the 12-row performance table with two bounded sentences retaining 17
   stages, 102/102 samples, zero failures, concurrency one, source revision, and
   not-capacity limitation.
3. Remove the full capability table and retain a short cited comparison.
4. Retain only the unified evidence/suggestion workflow figure.
5. Remove the recall equation/metric tutorial while retaining split, reviewer,
   bootstrap/randomization/Holm, QA-retriever, and synthetic-profile details.
6. Collapse repeated Discussion/Threats language without deleting negative
   results.
7. Reduce paper-only citations from 29 to about 20; do not delete thesis
   bibliography entries.
8. State 398 fully supported, 2 partial, 0 unsupported and that intervals omit
   AI-label uncertainty.
9. Correct Hal Daumé III BibTeX suffix syntax.
10. Add a generic IEEE Xplore build without bookmarks/links; apply final venue
    details only after the human venue decision.

Do not remove:

- the negative hybrid result and no corrected superiority;
- citation correctness 0.625, coverage 0.136, and 0/4 abstention;
- Finder delta 0.024 with CI crossing zero and all feasibility partial;
- same-AI silver/proxy and no-human boundaries;
- single-host/concurrency-one and three-document external limitations;
- exact-current reproduction status.

Verification:

~~~bash
make paper
.venv/bin/python scripts/validate_manuscripts.py
pdfinfo build/ieee-paper.pdf
rg -c '^\\bibitem' build/ieee-paper.bbl
qpdf --check build/ieee-paper.pdf
qpdf --json build/ieee-paper.pdf | rg '(/Outlines|/OpenAction|/Annots|/URI|/GoTo)'
~~~

Target: 5.8-6.0 readable pages, approximately 20 references, no layout abuse.
Render and inspect every page at 100 percent.

Likely commits:

1. Compress IEEE paper to six pages
2. Clarify paper evidence and bibliography
3. Add IEEE submission PDF profile

## Phase 10 — Exact candidate closure

Issues: REPRO-001, REPRO-003, and every issue whose verification changes
empirical or manuscript state.

From a clean selected candidate:

~~~bash
PYTHONPATH=backend .venv/bin/python -m pytest
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
make docs-validate
make thesis-assets-frozen
make thesis-compile
make paper
.venv/bin/python scripts/validate_manuscripts.py
scripts/reproduce_all.sh \
  --mode full \
  --source-db data/papers.db \
  --work-dir "tmp/reproduce/final-$(git rev-parse --short HEAD)"
(cd "tmp/reproduce/final-$(git rev-parse --short HEAD)" && \
  sha256sum -c REPRODUCTION_SHA256SUMS)
make release
~~~

Retain a sanitized evidence summary and checksums that do not redistribute
restricted PDFs or derived full text. Confirm that every manuscript claim points
to this exact revision or is explicitly labeled as historical.

Likely final commit:

Freeze peer-review candidate and reproducibility evidence

## Environment-dependent work not silently absorbed into this plan

SECURITY-001, OPS-001, and RATE-001 require an actual deployment boundary:
egress control, isolated parser resources, shared rate limiting/proxy identity,
and a database/concurrency choice. Codex can prepare configurations and tests,
but cannot claim those controls are deployed without the target environment.

Human-only closure remains in HUMAN_REQUIRED_ITEMS.md.
