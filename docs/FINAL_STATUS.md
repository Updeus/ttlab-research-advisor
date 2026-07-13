# Remediation Status

## Status boundary

The application, authoritative corpus/index design, and Phase 1–4 quality
evaluations are implemented and evidenced. The repository is not yet at final
submission closure: a committed full performance result, complete full
reproduction manifest, final current release bundle/tag, and final manuscript
rewrite/PDF preflight remain outstanding at this documentation snapshot.

This file reports what current artifacts prove. It does not treat planned work,
passing tests, or an older release archive as proof of the remaining gates.
Issue-by-issue closure is authoritative in
`docs/REVIEW_REMEDIATION_MATRIX.md`.

## Implemented workstreams

### Corpus, metadata, extraction, and index integrity

- 134 catalogue records are classified by source/PDF/eligibility state.
- 98 records have available local PDF content.
- 96 papers and 719 chunks are eligible in snapshot
  `corpus-04a010207327069a`.
- 36 records without usable text remain `needs_review` and are excluded from
  retrieval experiments.
- Two paper/PDF identity mismatches and their 16 chunks are explicitly
  excluded.
- The `Click to View` parser artifact is absent from active authors; author
  aliases and unresolved identity states are retained rather than guessed.
- Page extraction, scanned-page diagnostics, optional OCR, conservative section
  detection, PDF/title checks, and per-page provenance are implemented.
- Keyword, feature-hashing, and learned-dense representations cover all 719
  eligible chunks. Vector index manifests are authoritative; writes are atomic;
  partial demo output is isolated.

Current corpus details are in `artifacts/phase1/phase1_evidence.json` and
`docs/PHASE1_CORPUS_INDEX_REPORT.md`.

### Retrieval experiment

The source-derived AI-reviewed silver set contains 50 queries split 30
development/20 held-out test. Keyword, feature hashing, pinned learned dense,
heuristic hybrid, and development-tuned hybrid used identical corpus/candidate
controls. Correct set Recall, Hit, Precision, MRR, nDCG, and unanswerable
measures are stored with per-query rankings, 10,000-bootstrap intervals,
ablations, sensitivity, paired tests, Holm correction, and failures.

Held-out headline results:

| Mode | Set Recall@3 | MRR | nDCG@10 |
|---|---:|---:|---:|
| Keyword | 0.9395 | 0.9474 | 0.9580 |
| Feature hashing | 0.6535 | 0.5877 | 0.5823 |
| Dense | 0.9158 | 0.9386 | 0.9390 |
| Heuristic hybrid | 0.7947 | 0.8132 | 0.8293 |
| Tuned hybrid | 0.8561 | 0.8596 | 0.8713 |

No tuned-vs-baseline metric contrast rejected the null after experiment-family
correction. Tuned-hybrid MRR minus keyword was -0.0877 (95% CI -0.2368 to
0.0439). All modes failed to abstain on the one held-out unanswerable case. The
system therefore does not claim hybrid superiority or adequate out-of-corpus
rejection.

Evidence: `artifacts/phase2/retrieval/`.

### RAG faithfulness and citations

The 50-case AI-assisted formative review contains 46 answerable and four
unanswerable questions, 400 checkable claims, and 81 answer points. Strict
supported-claim rate was 0.995 (95% CI 0.9872–1.0000), citation correctness
0.625 (0.5641–0.6913), citation completeness 1.000, and strict answer-point
coverage 0.1358 (0.0674–0.2111). All four unanswerable cases failed to abstain.

The central limitation is explicit: structurally source-supported extractive
sentences can still be off-topic or incomplete. Forty-four cases were tagged
incomplete and 42 had off-topic retrieval. The Ollama service was unavailable,
so no local-model benchmark is reported.

Evidence: `artifacts/phase3/qa/`.

### Recommendations, topics/authors, and generated outputs

- The 28-profile recommendation proxy study reviewed 84 ranked items in each
  arm. Evidence-only relevance was 0.6310; full-Finder relevance was 0.6548;
  the paired difference 0.0238 had 95% CI -0.0238 to 0.0714. The full Finder
  did not demonstrate improvement.
- All 84 full-Finder items passed source-fidelity and fact/gap/suggestion
  separation checks, but all 84 feasibility judgments were partial. These are
  AI-proxy rubric outcomes, not student/supervisor validation.
- On 24 held-out topic cases, the controlled lexical method had micro precision
  0.6522, recall 0.4839, and F1 0.5556. The dense prototype had precision
  0.4175, recall 0.6935, and F1 0.5212. The more inspectable/higher-precision
  lexical path remains public.
- The author audit found no excluded-paper leakage, alias collision, authorship
  mismatch, or prohibited availability/endorsement wording. Thirteen possible
  same-person pairs remain unresolved.
- All 48 historical generated outputs received attributed AI review events. The
  14 paper artifacts and seven recommendations are `ai_reviewed`; 27 historical
  RAG answers are `needs_reprocess`. The event chain verified 48/48, and a
  second pass made zero changes.

Evidence: `artifacts/phase4/`.

### Frontend, security, privacy, and review

- React BrowserRouter supplies direct/reloadable routes for all primary public
  surfaces, a protected Admin route, browser history, route titles/focus, and a
  deterministic 404.
- Search, Ask, Finder, paper artifacts, and explorer views display available
  source locators, provider/model/time, review state, freshness, generated-
  content notices, and partial/unsupported warnings.
- Public questions and student-profile inputs are transient and are not stored
  in the database, browser storage, or URLs by default.
- Reviewer/admin mutations require environment-configured bearer actors unless
  the loopback-only insecure demo bypass is explicitly enabled. Production
  fails closed without HTTPS base URL, exact secure CORS/trusted hosts, and an
  active admin actor.
- Review events are attributable and append-only at the SQLite trigger layer
  with a verifiable hash chain.
- Request/body limits, public generation rate limiting, path/body-minimized
  logs, downloader allowlists/limits, local-path response redaction, and
  security-mode headers are implemented.
- Automated accessibility checks cover representative axe scans, skip/focus/
  route behavior, evidence labels, and horizontal overflow at 360, 768, 1024,
  and 1440 px. They are not a full WCAG or assistive-technology conformance
  audit.

Requirements and residual deployment responsibilities are documented in
`docs/FRONTEND_REQUIREMENTS.md`, `docs/SECURITY.md`, `docs/PRIVACY.md`,
`docs/THREAT_MODEL.md`, and `docs/DEPLOYMENT.md`.

### Reproducibility and external sanity

- `scripts/reproduce_all.sh`, `make reproduce-quick`, `make reproduce`, and
  `make release` implement isolated verification/rebuild/release entry points.
- The release builder is deterministic and allowlist-based, field-sanitizes
  restricted JSON content, and rejects PDFs, databases, indexes, private
  prompts/histories, local paths, and secret patterns.
- Three pinned CC BY Europe PMC XML documents were reacquired through the
  official API and passed 3/3 fixed lexical top-one checks. This is a format-
  compatibility sanity check only.
- The performance harness covers required pipeline/API/frontend operations with
  process-cold/warm repetitions and resource metadata, but no committed full
  result currently exists.
- A local release archive for older commit `d0d84aa6101a...` proves the builder
  path only. It is not the final current-commit bundle.

## Current engineering verification

The Phase 7 documentation pass re-ran:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest -q
npm --prefix frontend test -- --reporter=dot
npm --prefix frontend run build
```

Results:

- backend: 208 passed, 6 dependency/runtime deprecation warnings;
- frontend Vitest: 17 passed across four files; and
- TypeScript/Vite production build: passed.

These results establish engineering regression status only. Final closure still
requires the complete command matrix, E2E/audit/evaluation reruns, full
reproduction, current manuscript builds, and PDF/route visual inspection.

## Remaining local closure gates

1. execute and commit the full performance profile with documented hardware,
   median/p95, failures, RSS where available, and explicit scalability limits;
2. run the complete full-corpus reproduction command and retain its final
   manifest/logs without leaking restricted payloads;
3. rebuild and verify the sanitized release from the final clean commit, then
   prepare/create the documented release tag without changing visibility;
4. finish the evidence-generated 6–8 page IEEE paper and consistent thesis;
5. remove every visible placeholder/stale count, compile both documents, run
   local PDF preflight, and inspect every rendered page;
6. rerun backend/frontend/E2E/security/evaluation gates and visually inspect
   every primary route; and
7. reconcile every row in `docs/REVIEW_REMEDIATION_MATRIX.md` with exact final
   evidence.

These are active remediation tasks, not external blockers.

## External-only items

Repository work cannot supply an institutional ethics determination, participant
study, supervisor approval, official programme/title-page fields, funding or
conflict attestation, rights-holder permission to redistribute third-party
PDFs, production institutional ownership/contact procedures, or IEEE PDF
eXpress credentials. These are listed without red manuscript placeholders in
`docs/EXTERNAL_SUBMISSION_CHECKS.md`.

## Claim calibration

The current evidence supports an implemented and offline-evaluated source-
traceable research-intelligence system for one frozen laboratory corpus. It does
not support claims of a novel retrieval algorithm, validated human advisory
benefit, comprehensive topic expertise, production-scale performance, public
deployment approval, or broad external validity.
