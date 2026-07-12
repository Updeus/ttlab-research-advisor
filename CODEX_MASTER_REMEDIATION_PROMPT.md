# Codex master task: remediate the project audit and produce a defensible final paper

You are the principal engineer, empirical evaluator, research-methodology author, frontend reviewer, and manuscript editor for this repository:

- Repository: `https://github.com/Updeus/ttlab-research-advisor`
- Project: **TTLAB Research Intelligence Platform**
- Intended paper direction: **From Publication Archive to Research Advisor: A RAG-Based Platform for Academic Discovery**

This is an explicit, one-pass authorization to address multiple major phases. Do not stop after writing a plan, identifying issues, or making editorial changes. Continue through implementation, evaluation, documentation, manuscript revision, compilation, and final verification. Work in small, reviewable commits while completing the whole remediation program on one branch.

## 1. Non-negotiable operating rules

1. Read `AGENTS.md`, `AUTHOR_REVIEW.md`, `README.md`, the complete `paper/` and `thesis/` sources, all evaluation documents, backend code/tests, frontend code, data schemas, generated evidence, and build scripts before editing.
2. Re-audit the **actual current `main` HEAD**. The earlier review referenced commit `713ea5c`, but the repository has moved forward. Do not copy stale counts, paths, claims, dates, or conclusions into the final paper.
3. Create and work on a branch named `codex/fix-audit-and-finalize-paper`. Do not rewrite history and do not merge to `main` automatically.
4. Create `docs/REVIEW_REMEDIATION_MATRIX.md` before implementation. Give every issue from the supplied review a stable ID, severity, evidence, intended fix, verification command, final status, and residual limitation. No issue may silently disappear.
5. Do not ask the user to review routine technical, editorial, labeling, or UI decisions. Make the most defensible evidence-based choice and record it in `docs/DECISION_LOG.md`.
6. Do not fabricate papers, metadata, permissions, ethics numbers, participants, assessors, ratings, citations, metrics, model results, system behavior, or statistical significance.
7. Perform the work expected of a meticulous human reviewer, including inspecting source passages and generated outputs and recording rationales. However, identify the reviewer honestly as an **AI reviewer** (for example, `codex-ai-review`) in data and disclosures. Never describe Codex as a human participant, independent assessor, supervisor, or ethics-approved reviewer. AI-created labels must be described as AI-assisted or silver labels, not human gold labels.
8. User-provided fact: **TTLAB gave explicit permission to undertake this project.** Treat that as project/corpus authorization. Do not turn it into a claim of research-ethics-board approval, blanket copyright ownership, or permission to redistribute every third-party PDF unless documentary evidence supports those stronger claims.
9. Unless actual participant evidence already exists, conduct **no human-participant study** in this pass and make no user-benefit, student-satisfaction, supervisor-approval, or human-usability claim. Use a transparent AI-assisted formative review where useful, report its limitations, and revise the paper’s claims accordingly.
10. Do not change repository visibility or publish restricted PDFs. Build a sanitized reproducibility release containing only code and redistributable metadata/derived artifacts.
11. Preserve existing API/data contracts where practical. Add migrations and compatibility layers when schemas change. Keep the application runnable after every phase.
12. Use exact, pinned model/provider names, revisions or digests, prompts, parameters, seeds, package versions, and hardware descriptions for every reported experiment.
13. A passing test suite is engineering evidence, not retrieval or answer-quality evidence. Keep these claims separate in code, UI, and paper.
14. Do not declare completion while visible `AUTHOR INPUT REQUIRED`, placeholder performance data, stale counts, known index inconsistencies, or unsupported effectiveness claims remain in final artifacts.

## 2. Required final outcomes

Deliver all of the following:

1. A repaired, internally consistent, reproducible application.
2. A complete and authoritative full-corpus index for every eligible current chunk.
3. A modular learned dense-retrieval baseline in addition to keyword and feature-hashing baselines.
4. Executed retrieval, RAG faithfulness, citation, recommendation-proxy, topic/author, performance, and ablation experiments with raw results.
5. A polished, responsive, accessible frontend that exposes evidence, review state, evaluation state, and the distinction between facts and suggestions.
6. A concrete methodology, not merely a proposed methodology.
7. A strong IEEE-style full paper of approximately 6–8 substantive pages, plus an updated thesis where the repository already contains thesis sources.
8. A sanitized versioned reproducibility bundle and manifest.
9. A final issue-closure report mapping every review issue to code, data, tests, experiment results, manuscript text, or a clearly stated external-only limitation.

## 3. Phase 0 — baseline, evidence freeze, and issue verification

Before changing behavior:

- Record `git status --short`, current commit, branch, remotes, and whether the working tree is dirty.
- Record date/time, OS, CPU, RAM, GPU if present, Python, Node, npm, TeX, database, and relevant package versions.
- Run the current backend tests, frontend build, smoke checks, evidence collection, paper build, and thesis build. Save all logs under `artifacts/baseline/`.
- Back up the runtime database and current index files before migrations or rebuilds.
- Generate a pre-change manifest of papers, PDFs, extracted text, pages, chunks, authors, topics, artifacts, answers, recommendation runs, review events, evaluation files, and hashes.
- Verify each audit finding against current HEAD. Mark findings as `confirmed`, `already_fixed`, `changed_since_audit`, or `not_reproducible`, with evidence.
- Fix documentation contradictions discovered during the re-audit.

Commit this phase separately.

## 4. Phase 1 — data, extraction, metadata, identity, and index integrity

### 4.1 Authoritative derived-state design

Replace the ambiguous SQLite/JSON split with a clear authoritative manifest or consolidated storage model. The index manifest must include at least:

- corpus snapshot ID and hash;
- eligible paper and chunk counts;
- ordered chunk IDs and source hashes;
- provider and model name;
- exact model revision/digest;
- vector dimension and normalization;
- creation timestamp;
- code commit;
- index file hash;
- configuration hash;
- completeness status.

Index writes must be atomic. Database statuses must be updated transactionally and omitted chunks must be invalidated. A bounded demo rebuild must never overwrite or falsely validate the complete production/demo index. Startup and evaluation must fail loudly on manifest/status mismatch.

Add regression tests for the 25-of-756 style failure, stale statuses, partial writes, corpus changes, and bounded demo rebuilds.

### 4.2 Rebuild complete retrieval indexes

- Rebuild keyword/FTS and vector indexes for **all currently eligible chunks**, not a hard-coded historical count.
- Verify one-to-one coverage against the frozen manifest.
- Expose index coverage and manifest health through the API and Evaluation/Admin UI.
- Do not use database `embedding_status` as the sole source of truth.

### 4.3 Clarify feature hashing and add learned dense retrieval

- Rename the current 256-dimensional feature-hashing capability everywhere so it is not described as learned semantic search. Keep it as a reproducible lexical-feature vector baseline.
- Add a provider-modular learned dense encoder using a lightweight, reproducible sentence-transformer suitable for local use. Select and justify the model based on corpus size, licensing, offline operation, and hardware. Pin the exact revision or artifact hash.
- Preserve an offline fallback. The application must degrade clearly rather than fail silently when the dense model is unavailable.
- Add CLI/API/UI support for at least: keyword, hashing, dense, and hybrid retrieval.

### 4.4 PDF acquisition, extraction, and OCR

- Attempt deterministic remediation of missing/failed PDFs only through permitted source URLs and official/public endpoints. Do not bypass authentication, paywalls, robots controls, or access restrictions.
- Classify every unavailable paper: no PDF URL, forbidden, not found, timeout, invalid PDF, scanned PDF, extraction failure, or permission-restricted.
- Add scanned-document detection and an optional OCR fallback with page-level provenance, confidence/status, and review flags. The core system must still work when OCR dependencies are absent.
- Add extraction diagnostics and tests for malformed, scanned, blank, and mixed-content PDFs.
- Freeze the final eligible experimental corpus and make all inclusion/exclusion rules explicit.

### 4.5 Section detection

- Improve heading/layout heuristics so `unknown` sections are reduced where evidence permits.
- Create a stratified, source-backed review sample and report actual section-label accuracy/coverage. Labels produced by Codex must be identified as AI-reviewed silver labels.
- Preserve `unknown` when evidence is insufficient; do not force false labels.

### 4.6 Metadata and author identity

- Fix the parser that produced `Click to View` as an author and repair all affected links through an idempotent migration/rebuild.
- Add canonical author identities, aliases, normalized names, merge/split review state, and persistent identifiers only when verified.
- Add DOI, abstract, keyword, venue, and date provenance/review fields. Populate only from verified source evidence; leave fields empty and `needs_review` otherwise.
- Ensure author-expertise views operate on canonical identities and explicitly state that evidence comes only from indexed publications.

Commit this phase separately.

## 5. Phase 2 — retrieval experiment, baselines, tuning, ablations, and statistics

### 5.1 Evaluation set

Create a reproducible, source-derived **AI-reviewed silver retrieval set**, not a falsely labeled human gold set. Use at least 40–60 questions, stratified across:

- exact factual lookup;
- methods;
- results;
- limitations and future work;
- title/author/venue;
- topic/application;
- comparison;
- broad intent;
- multi-paper synthesis;
- hard negatives;
- unanswerable/out-of-corpus cases.

For every judgment, store the relevant paper IDs, supporting chunk/page evidence, query category, rationale, reviewer type, timestamp, and review pass. Use a two-pass process: one pass creates judgments; a later pass verifies them in shuffled order without looking at system rankings. Record disagreements and adjudication. Call this annotation consistency, not human inter-rater agreement.

Split the set into development and held-out test partitions. Do not tune on the test set.

### 5.2 Correct metric implementation

The existing implementation reportedly calls a binary hit rate “Recall@k.” Correct this. Report and test distinct definitions for:

- set Recall@3, Recall@5, and Recall@10;
- Hit@3, Hit@5, and Hit@10;
- MRR;
- nDCG@10 where graded relevance exists;
- Precision@k where meaningful;
- unanswerable-query false-positive/abstention behavior.

Add unit tests with hand-computed examples.

### 5.3 Baselines and comparisons

Run all modes over the identical frozen corpus, query set, filters, and cutoffs:

- keyword/FTS or BM25-equivalent lexical baseline;
- feature hashing baseline;
- learned dense baseline;
- existing hybrid;
- a tuned hybrid if the development set supports tuning.

If weights remain heuristic, label them as heuristic. If tuned, store the search space, objective, development results, final selected weights, and test-only evaluation.

### 5.4 Ablations and sensitivity

Ablate individually and cumulatively:

- query expansion;
- metadata boosts;
- section boosts;
- evidence adjustments;
- topic adjustments;
- diversity penalties;
- recommendation/retrieval weight terms where applicable.

Run sensitivity analysis around selected weights. Save per-query rankings and scores, not only aggregates.

### 5.5 Statistical analysis and errors

- Report bootstrap 95% confidence intervals over queries.
- Use paired tests appropriate to the metric/data and document assumptions. Correct for multiple comparisons where needed.
- Add a systematic error taxonomy covering extraction, intent mismatch, lexical mismatch, semantic mismatch, topic/identity error, over-broad expansion, ranking diversity, and corpus absence.
- Publish all cases, including failures, in sanitized evaluation artifacts.

Commit this phase separately.

## 6. Phase 3 — RAG answer faithfulness, citation correctness, and model reproducibility

Create a stratified QA set linked to the retrieval set, including answerable and unanswerable questions. For each answer:

- segment the answer into atomic, checkable claims;
- identify cited paper/chunk/page evidence;
- judge claim entailment/support;
- judge citation correctness;
- judge citation completeness;
- judge answer-point completeness;
- detect unsupported general knowledge;
- verify abstention on insufficient evidence.

Codex may perform the review work, but persist `reviewer_type = ai` and report the result as AI-assisted formative evaluation. Do not claim human faithfulness judgments.

Report at least:

- supported-claim rate;
- citation precision/correctness;
- citation completeness;
- answer-point coverage;
- unsupported-claim rate;
- abstention accuracy;
- results by question category;
- confidence intervals and error taxonomy.

Add an optional automated entailment/NLI check only as a supplement, never as unquestioned ground truth.

Compare the offline/extractive answerer with any available local Ollama model on the same cases. Record exact model tag/digest, quantization, prompt, temperature, context limits, hardware, cold/warm latency, failures, and fallback state. If Ollama is unavailable, report that fact and do not invent a benchmark.

Strengthen runtime behavior so source identifiers, pages, snippets, warnings, provider metadata, timestamps, and review status survive end to end. “Grounded” must not mean factually correct unless claim-level support has been checked.

Commit this phase separately.

## 7. Phase 4 — Thesis Extension Finder, topics, authors, summaries, podcasts, and review

### 7.1 Recommendation evaluation

Create at least 20–30 diverse student/project profiles spanning interests, skills, time, project type, data constraints, preferred difficulty, and avoid-topics. For each profile, compare:

1. an evidence-only retrieval baseline that returns ranked papers and source passages; and
2. the full Thesis Extension Finder.

Review each recommendation for:

- source fidelity;
- paper relevance;
- separation of paper facts, explicit future work, inferred gaps, and new suggestions;
- novelty caution;
- feasibility for skills/time/data;
- MVP scope;
- stretch-goal appropriateness;
- risk calibration;
- required skills;
- evaluation-plan quality;
- usefulness as an AI proxy judgment.

Persist rationales and citations. Report this as AI-assisted proxy review, not student/supervisor validation. Do not claim that a recommendation is novel, feasible, or supervisor-approved without external confirmation.

Add sensitivity analysis for recommendation weights. If weights remain hand-authored, state that clearly. Add the evidence-only baseline as a user-visible mode and use it in the experiment.

### 7.2 Topic and author evaluation

- Resolve author identities before evaluating expertise links.
- Validate the fixed lexical taxonomy as a controlled vocabulary on a stratified sample, including multi-label and `other/unknown` cases.
- Report precision/coverage using AI-reviewed silver labels, with explicit limitations.
- Compare the fixed taxonomy to a lightweight learned or embedding-based alternative only if the comparison is reproducible and useful; otherwise justify retaining the controlled vocabulary.
- Never imply researcher availability, endorsement, or expertise beyond publication evidence.

### 7.3 Generated outputs and review events

Regenerate or inspect all current RAG answers, extension recommendations, summaries, technical summaries, contributions, methods, limitations, future work, possible extensions, skills, evaluation plans, and podcast scripts. Record AI review events with reviewer identity, status, rationale, cited evidence, and corrections. Introduce a distinct status such as `ai_reviewed` so AI review is not confused with human approval.

Commit this phase separately.

## 8. Phase 5 — frontend, API, privacy, authentication, security, and deployment requirements

Create `docs/FRONTEND_REQUIREMENTS.md` and ensure the implementation and paper describe the frontend as a core part of the research-intelligence platform, not decoration.

### 8.1 Required public surfaces

Preserve and improve these current surfaces:

- Dashboard;
- Paper Browser and Paper Detail;
- Search;
- Ask TTLAB;
- Thesis Extension Finder;
- Topic/Author Explorer;
- Evaluation Dashboard;
- Admin Review.

Add route-based/deep-linkable navigation if the current state-only navigation prevents reproducible URLs, browser history, or direct links.

### 8.2 Evidence and responsible-AI UX

Every relevant screen must show:

- source paper, chunk, page/section, and snippet;
- whether text is extracted fact, paper-stated future work, inference, or system suggestion;
- provider/model and timestamp where applicable;
- review status and reviewer type;
- unsupported/partial-grounding warnings;
- data/index/evaluation freshness;
- clear generated-content notices;
- an evidence-only alternative where relevant.

The Thesis Extension Finder must clearly display profile inputs, ranked papers, fit rationale, extension idea, MVP, stretch goals, risks, skills, data needs, evaluation plan, related work, and potential researcher fit as evidence-derived—not supervisor assignment.

### 8.3 Accessibility and responsiveness

Target WCAG 2.2 AA where practical:

- keyboard-only operation;
- visible focus;
- semantic landmarks/headings;
- accessible form labels and validation;
- sufficient contrast;
- reduced-motion support;
- screen-reader names;
- text alternatives for charts;
- no essential color-only encoding;
- no horizontal overflow at 360 px;
- tested layouts around 360, 768, 1024, and 1440 px.

Add loading, skeleton, empty, error, retry, stale-data, offline-provider, and no-evaluation states. Do not show zero as though it were a measured score when evaluation has not run.

### 8.4 Privacy by minimization

Student interests, skills, timelines, constraints, and project preferences must not be persisted by default. Keep them client-side/in-request unless the user explicitly opts in. If persistence is supported, add purpose, retention, deletion, export, and access-control behavior. Add a concise privacy notice.

### 8.5 Admin authentication and auditability

Implement the smallest defensible authentication/authorization layer for public deployment:

- public read-only routes;
- authenticated reviewer/admin routes;
- no default or committed secret;
- environment-based configuration;
- secure password handling or a documented external identity boundary;
- protected review state transitions;
- reviewer attribution;
- immutable audit events;
- CSRF/CORS/session/token protections appropriate to the chosen design.

Keep a local-demo mode, but visibly distinguish it from production security.

### 8.6 Security and deployment

Create/update:

- `docs/THREAT_MODEL.md`;
- `docs/SECURITY.md`;
- `docs/PRIVACY.md`;
- `docs/DEPLOYMENT.md`.

Address input limits, file validation, PDF bombs, path traversal, SSRF in downloaders, XSS, injection, secrets, rate limiting, logging, monitoring, backups, dependency auditing, and incident/correction procedures. Add targeted tests.

### 8.7 Frontend verification

Add automated component/integration tests and a small Playwright or equivalent end-to-end suite covering all primary surfaces, citations, error states, responsive behavior, keyboard navigation, and admin protection. Capture current, accurate screenshots for the paper after final data/evaluation state is loaded.

Commit this phase separately.

## 9. Phase 6 — performance, scalability, external-validity sanity check, and reproducibility

Benchmark on documented hardware with repeated cold and warm runs:

- discovery/import;
- PDF extraction and OCR where used;
- chunking;
- keyword, hashing, and dense indexing;
- keyword, hashing, dense, and hybrid retrieval;
- answer generation;
- extension recommendation;
- key API endpoints;
- frontend production build and representative page load/API response times.

Report median, p95, repetitions, memory where measurable, corpus size, concurrency assumptions, and failure rates.

To reduce the single-laboratory limitation, add a small, clearly separated external sanity corpus of openly licensed scholarly documents through an official source/API if this can be done without violating permissions or destabilizing the project. Use it only as an external-validity check, not as evidence about TTLAB. If no suitable corpus can be acquired reproducibly, retain the limitation and document the attempted procedure.

Create a one-command reproducibility entry point such as `scripts/reproduce_all.sh` or a `make reproduce` target that:

1. verifies dependencies;
2. builds/fixes the database from allowed inputs;
3. extracts/chunks/indexes;
4. runs all experiments;
5. generates evidence tables/figures;
6. runs tests and frontend build;
7. compiles paper and thesis;
8. runs PDF preflight;
9. emits a final manifest and checksums.

Commit this phase separately.

## 10. Phase 7 — executed methodology and research documentation

Create or substantially update:

- `docs/METHODOLOGY.md`;
- `docs/EVALUATION_PROTOCOL.md`;
- `docs/FRONTEND_REQUIREMENTS.md`;
- `docs/ETHICS_AND_GOVERNANCE.md`;
- `docs/DATA_AND_ARTIFACT_AVAILABILITY.md`;
- `docs/REPRODUCIBILITY.md`;
- `docs/REVIEW_REMEDIATION_MATRIX.md`;
- `docs/DECISION_LOG.md`.

The methodology must be an **executed artefact-oriented design-science/engineering case study plus controlled offline evaluation**, not only a future proposal. It must define:

- research aim;
- explicit RQ1–RQ5 (or a better justified set);
- objectives and contributions;
- unit of analysis;
- corpus snapshot, inclusion/exclusion, and provenance;
- system architecture and frontend requirements;
- retrieval representations and baselines;
- development/test split;
- evaluation cases and AI-review procedure;
- metrics with formulas;
- tuning and ablation plan;
- statistical analysis and confidence intervals;
- performance methodology;
- error analysis;
- reproducibility controls;
- ethics, permissions, privacy, responsible AI, and disclosure;
- construct, internal, external, and reproducibility threats.

Use the following conservative ethics/authorization logic:

- State that TTLAB explicitly authorized the project and use of the laboratory corpus, based on the user-provided fact.
- State that this pass reports software/document experiments and AI-assisted review, with no recruited human participants unless verifiable participant records exist.
- Do not claim IRB/REC approval or exemption without an approval/exemption record.
- State that TTLAB authorization does not automatically confer redistribution rights over third-party PDFs; exclude restricted PDFs from the release and document the policy.
- Explain privacy minimization for student-profile inputs.
- Add an explicit disclosure of Codex/LLM assistance in coding, evaluation-label preparation, analysis, and manuscript editing, consistent with institutional policy and without understating its role.

Commit this phase separately.

## 11. Phase 8 — rewrite the IEEE paper and update the thesis

### 11.1 Positioning and title

Choose a title supported by the final evidence. If advisory usefulness is not human-validated, use restrained wording such as:

> Engineering and Evaluating a Source-Traceable Research-Intelligence Platform for a Laboratory Corpus

or

> From Publication Archive to Source-Traceable Research Advisor: Design and Offline Evaluation of a Laboratory RAG Platform

Do not use a title that implies validated human advisory benefit unless that evidence exists.

Define **source-traceable** precisely as persistent paper/chunk/page/section provenance and review state; it is not synonymous with factual entailment.

### 11.2 Required paper structure

Produce a substantive IEEE conference paper of approximately 6–8 pages without padding. Include:

1. concise abstract: problem, system, executed methodology, principal quantitative results, limitations, contribution;
2. introduction with explicit RQ1–RQ5;
3. 3–5 enumerated contributions, separating engineering and empirical contributions;
4. structured related work covering scholarly discovery, expert finding, RAG, RAG evaluation, scholarly recommendation, human-in-the-loop review, and relevant public-facing research systems;
5. a comparison table against prior systems using dimensions such as full-text ingestion, page-level citations, source/claim separation, thesis recommendation, admin review, evaluation, and public frontend;
6. methodology and experimental design;
7. system architecture, including frontend, FastAPI services, intelligence/retrieval, persistence, review, and evaluation layers;
8. a legible two-column architecture figure and a simplified RAG/recommendation workflow;
9. one compact, current interface screenshot with an informative caption and alt-text source;
10. corpus/data inventory clearly labeled as a snapshot, separate from quality/performance results;
11. retrieval baseline, dense comparison, ablation, statistics, and error analysis;
12. claim/citation faithfulness results;
13. recommendation AI-proxy evaluation and evidence-only comparison;
14. topic/author review results;
15. performance results;
16. discussion;
17. threats to validity: construct, internal, external, and reproducibility;
18. ethics, permissions, privacy, security, responsible AI, and AI-use disclosure;
19. code/data/artifact availability;
20. conclusion calibrated to the evidence.

Reference every figure and table in the body. Ensure figures are legible at final size. Do not mix inventory counts with persisted operational state or quality metrics. Do not present counts, test totals, or structural traceability as accuracy.

### 11.3 Claims and results

- Regenerate every number from frozen artifacts; do not hand-copy stale counts.
- Report actual corpus coverage and explain exclusions.
- Report actual index coverage from the authoritative manifest.
- Use correct metric names and confidence intervals.
- Publish failures and negative results.
- Move test/build counts to engineering verification, not effectiveness results.
- Clearly label AI-review results and the absence of a human study.

### 11.4 Literature and citations

- Use verified bibliographic records from primary papers or official project documentation.
- Verify title, authors, year, venue, pages, DOI/URL, and citation relevance.
- Correctly describe the Narine and Hosein precursor: publication collection/display, lay summarization, notifications, manual podcast workflow, and RAG as future work.
- Do not invent citations or cite a paper for a claim it does not support.

### 11.5 Author-input markers and declarations

Remove all visible red `AUTHOR INPUT REQUIRED` markers from final PDFs. Do not replace them with invented facts. For information unavailable from evidence:

- omit it when optional;
- use conservative, non-claiming wording when necessary;
- place genuine external-only attestations in `docs/EXTERNAL_SUBMISSION_CHECKS.md`, not as red manuscript text.

Do not invent funding or conflict-of-interest declarations. Use only evidence-supported wording, and explicitly note in the external submission checklist if the venue requires an author attestation not available in the repository.

### 11.6 Format, metadata, and accessibility

- Select a documented default IEEE conference profile (use US Letter unless an existing venue specification says otherwise) and centralize venue-specific options in a small configuration file.
- Add PDF title, author, subject, and keywords metadata.
- Use accessible source practices: descriptive captions, alt-text source, logical headings, non-color-only figures, readable type, and tagged PDF support if the installed IEEE/LaTeX toolchain can produce it without corrupting layout.
- Run `latexmk`, bibliography checks, `chktex` or equivalent, `pdfinfo`, `pdffonts`, and a PDF structural checker. Confirm page size, page count, embedded fonts, no Type 3 fonts, metadata, links, and no overfull/illegible content.
- IEEE PDF eXpress/Checker cannot be claimed complete without venue credentials. Perform all local preflight checks and record that external venue validation is pending only if credentials are unavailable.

### 11.7 Availability and release

- Create a versioned sanitized release bundle with code, schemas, seeds that may be shared, evaluation cases/labels, raw results, prompts/configs, figures, hashes, and reproduction instructions.
- Exclude restricted PDFs, private data, secrets, and unlicensed content.
- Tag the final commit or prepare a release tag. Do not make the private repository public without explicit authorization.
- In the paper, state exactly what is available and under what conditions; do not imply that private/restricted data are public.

Update the full thesis consistently so it does not contradict the paper. Remove proposed-only language where experiments were executed, but retain honest limitations around human validation.

Commit this phase separately.

## 12. Final verification gates

Run and save the exact commands and outputs appropriate to the final repository, including at minimum:

```bash
git status --short
git rev-parse HEAD
PYTHONPATH=backend python -m pytest
cd frontend && npm ci && npm run build
```

Also run:

- backend lint/type checks if configured or added;
- frontend unit/integration tests;
- end-to-end browser tests;
- dependency/security audits (`pip-audit`, `npm audit`, or documented equivalents);
- all retrieval/QA/recommendation/topic/performance evaluations;
- the full reproducibility command;
- paper and thesis builds;
- PDF preflight and page-image inspection.

Visually inspect every final PDF page and every primary frontend route. Verify that tables, screenshots, citations, footnotes, equations, and figures are readable and referenced.

No final metric may be present unless its raw result, configuration, input set, and code path exist in the release bundle.

## 13. Definition of done

The task is complete only when:

- every audit issue has a status and evidence in the remediation matrix;
- all feasible project defects are fixed and tested;
- all eligible chunks are covered by authoritative indexes;
- metadata/author parser defects are migrated;
- dense retrieval, baselines, and ablations are executed;
- retrieval metrics are correctly named and computed;
- claim-level citation evaluation is executed;
- recommendation/topic/author AI-proxy reviews are executed and honestly labeled;
- frontend requirements are documented and implemented;
- admin/security/privacy/accessibility controls are materially improved;
- the methodology describes what was actually done;
- the paper is a polished, evidence-supported 6–8 page IEEE manuscript;
- the thesis is consistent with the final system and results;
- all visible placeholders are removed from final PDFs;
- tests/builds/evaluations/reproduction succeed or an exact, non-fabricated external blocker is recorded;
- a sanitized release manifest and checksums exist;
- the working tree contains only intentional changes.

## 14. Final response format

At completion, provide:

1. branch and final commit;
2. concise summary by workstream;
3. issue matrix counts: closed, mitigated by claim reduction, and external-only;
4. actual corpus/index counts;
5. retrieval baseline/ablation results with confidence intervals;
6. faithfulness/citation results;
7. recommendation/topic/author proxy-review results, clearly labeled AI-assisted;
8. performance results and hardware;
9. frontend requirements implemented and test coverage;
10. security/privacy/accessibility changes;
11. paper title, page count, build path, and PDF preflight result;
12. thesis build path;
13. tests/build/evaluation commands and outcomes;
14. release bundle path/tag and excluded restricted content;
15. remaining external-only items such as venue PDF eXpress credentials or author attestations.

Do not finish with a recommendation that the user manually inspect every item. The repository evidence, automated checks, source-backed AI review, and issue matrix must carry the review burden. Be explicit, however, about anything that only a human institution, ethics body, venue, or legal rights-holder can legitimately attest.
