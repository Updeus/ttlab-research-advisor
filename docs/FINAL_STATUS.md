# Historical v1 Remediation Status

> **Superseded checkpoint.** This file records the pre-peer-review-audit v1
> evidence boundary and its then-current counts. It is retained because the
> negative results and revision-specific measurements remain part of the
> research record. It must not be used as current checkout status. Current
> issue disposition, manuscript counts, commands, and candidate provenance are
> reported in `docs/peer_review_readiness/FINAL_READINESS_REPORT.md`.

## Closure boundary

The earlier July 2026 remediation was reported complete at its v1 candidate
boundary. The
authoritative register contains 89 findings: 87 are `closed`, `RAG-01` is
`mitigated by claim reduction`, and `PAPER-14` is `external-only`. No finding is
silently omitted or described as closed by an invented experiment, metric,
human study, institutional decision, or immutable final commit hash.

Two delivery gates are deliberately fail-loud. The `REP-*` and `RELEASE-*`
closures are valid only if the exact committed candidate passes the full
isolated reproduction and release-verification commands in
`docs/REVIEW_REMEDIATION_MATRIX.md`. A nonzero command, invalid manifest, dirty
source snapshot, checksum mismatch, or release exclusion finding invalidates
those rows and the delivery must not be represented as complete.

The issue-by-issue record is
`docs/REVIEW_REMEDIATION_MATRIX.md`; external author, institution, rights-holder,
and venue decisions are in `docs/EXTERNAL_SUBMISSION_CHECKS.md`.

## Delivered manuscripts

- `build/ieee-paper.pdf` is an eight-page US Letter IEEEtran paper titled
  *An AI-Based Platform for Content Summarization and Idea Generation using a
  Research Lab’s Output*.
- `build/thesis.pdf` is a 74-page A4 MSc Data Science project thesis.
- Both documents identify Jarod Esareesingh, the Department of Computing &
  Information Technology, The University of the West Indies,
  `jarod.esareesingh@my.uwi.edu`, and Trinidad and Tobago. No city is shown.
- Editable LaTeX, generated table/figure sources, BibTeX, evidence snapshots,
  and author-review material remain in `paper/`, `thesis/`,
  `thesis/PROJECT_EVIDENCE.md`, `thesis/references.bib`, and
  `AUTHOR_REVIEW.md`.

The source preflight covers 38 manuscript source files, 30 floats, 81 citation
uses, and 32 BibTeX entries. The compiled PDFs pass local structure, metadata,
font, unresolved-reference, visible-marker, overflow, and rasterization gates;
all eight paper pages and all 74 thesis pages were rendered and visually
inspected. Fonts are embedded and no Type 3 fonts are present. The PDFs are
untagged: this repository makes no PDF/UA or WCAG-conformance claim, and IEEE
PDF eXpress remains a venue-controlled external check.

## Implemented and evaluated workstreams

### Corpus, extraction, and indexes

- 134 catalogue records, 98 available local PDFs, and 96 eligible papers form
  the frozen local snapshot.
- The database contains 735 raw chunks; 719 are eligible and indexed by
  keyword, 256-dimensional feature hashing, and pinned 384-dimensional learned
  dense representations.
- Thirty-six records without eligible text remain review-required. Two
  mismatched PDFs and their 16 chunks are explicitly excluded.
- Page-aware extraction, scanned/blank/mixed diagnostics, optional OCR states,
  conservative section detection, title/PDF identity checks, and page/source
  provenance are implemented.
- The 40-case section silver evaluation reports 0.900 accuracy, 0.8917 macro
  precision, and 0.9040 macro recall. The 199 eligible `Unknown` section labels
  remain visible rather than being guessed.

Evidence: `artifacts/phase1/phase1_evidence.json` and
`docs/PHASE1_CORPUS_INDEX_REPORT.md`.

### Retrieval

The source-derived AI-reviewed silver set contains 50 queries split into 30
development and 20 held-out test cases. All retrieval modes use the same
eligible candidate pool. Held-out results are:

| Mode | Set Recall@3 | Set Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|
| Keyword | 0.9395 | 1.0000 | 0.9474 | 0.9580 |
| Learned dense | 0.9158 | 0.9895 | 0.9386 | 0.9390 |
| Feature hashing | 0.6535 | 0.7035 | 0.5877 | 0.5823 |
| Heuristic hybrid | 0.7947 | 0.9167 | 0.8132 | 0.8293 |
| Development-tuned hybrid | 0.8561 | 0.9254 | 0.8596 | 0.8713 |

No tuned-versus-baseline contrast rejected the null after Holm correction. All
modes returned a false positive for the single held-out unanswerable case, so
the work claims neither hybrid superiority nor adequate out-of-corpus
rejection. Feature hashing is consistently described as a lexical-feature
baseline, not semantic retrieval.

Evidence: `artifacts/phase2/retrieval/`.

### RAG faithfulness and citations

The 50-case offline-extractive formative review contains 46 answerable and four
unanswerable questions, 406 segmented claims, 400 checkable claims, and 81
answer points. Of the checkable claims, 398 were supported, two partial, and
none unsupported. Strict supported-claim rate was 0.995 (95% CI
0.9872--1.0000), citation correctness 0.625 (0.5641--0.6913), citation
completeness 1.000, and strict answer-point coverage 0.1358
(0.0674--0.2111). All four unanswerable cases failed to abstain.

Runtime `grounded` is retained as a backward-compatible structural/weak-lexical
status. UI, API, documentation, and manuscripts no longer present it as claim
entailment or factual correctness. The service therefore remains limited by
off-topic and incomplete answers even when cited sentences are structurally
traceable. The Ollama service was unavailable, so no local-model quality or
latency comparison is reported.

Evidence: `artifacts/phase3/qa/`.

### Recommendations, topics/authors, and generated review

- The 28-profile recommendation proxy study assessed 84 ranked items per arm.
  Evidence-only relevance was 0.6310 and full-Finder relevance 0.6548; the
  paired difference was 0.0238 (95% CI -0.0238 to 0.0714), so improvement was
  not demonstrated.
- All 84 full-Finder feasibility judgments were partial, and 12 of 84
  evaluation-plan judgments were partial. The sensitivity study used 21
  perturbations plus the default, for 22 configurations total. These are
  synthetic-profile, AI-proxy results rather than student or supervisor
  validation.
- On 24 held-out topic cases, the controlled lexical method achieved micro
  precision 0.6522, recall 0.4839, F1 0.5556, and coverage 0.875. The dense
  prototype achieved 0.4175, 0.6935, 0.5212, and 0.9583 respectively.
- The author audit found no excluded-paper leakage, alias collision, authorship
  mismatch, or prohibited availability/endorsement wording; 13 possible
  same-person pairs remain unresolved.
- Forty-eight historical outputs have hash-chained attributed AI review events:
  14 paper artefacts and seven recommendations are `ai_reviewed`; 27 historical
  answers are `needs_reprocess`. The audit is idempotent and is not human
  approval.

Evidence: `artifacts/phase4/`.

### Performance and scalability boundary

The validated full profile contains 17 stages, three process-cold and three
process-warm repetitions per stage, 102 timing samples, 102 peak-RSS samples,
and zero failures. The strict validator records `status: valid` in
`artifacts/phase6/performance/performance_validation.json`. The benchmark ran
CPU-only under WSL2 on an AMD Ryzen 7 5800X with 16 logical CPUs and about
3.8 GiB visible RAM.

Representative cold/warm median latencies and observed peak RSS include PDF
extraction 15.466/12.874 s and 112.6 MiB, dense indexing 145.005/66.169 s and
751.5 MiB, keyword retrieval 9.809/8.091 s and 111.8 MiB, learned-dense
retrieval 84.487/12.215 s and 563.5 MiB, answer generation 83.355/9.842 s and
571.9 MiB, and the frontend build 31.145/30.763 s and 461.2 MiB. These are
three-repetition single-machine observations, not throughput, concurrency,
capacity, SLO, production-scale, or OCR-quality claims. The warm p95 includes
the first warm model load, and the zero-unit OCR stage is overhead rather than
measured OCR latency.

Evidence: `artifacts/phase6/performance/performance_full_results.json`,
`artifacts/phase6/performance/performance_validation.json`, and
`docs/PHASE6_PERFORMANCE_AND_SCALABILITY.md`.

### External format sanity

Three pinned CC BY Europe PMC JATS/XML documents were reacquired through the
official API, mapped by a dedicated parser into the production chunking
contract, and passed 3/3 fixed lexical top-one checks. This is a small
format-compatibility sanity check, not the main PDF ingestion path and not
cross-domain retrieval-quality evidence. Raw XML remains excluded from the
release.

## Engineering and interface verification

The final checkpoint records:

- backend Pytest: 249 passed, with six dependency deprecation warnings;
- frontend Vitest: 19 passed across five files;
- frontend Playwright: six Chromium tests passed;
- TypeScript/Vite production build: passed;
- application smoke gate: 17 pass, zero warning/failure, with all three indexes
  at 719/719 eligible chunks;
- documentation validator: 37 Markdown files, 23 local links, zero errors;
- Python lock validation: all 92 exact pins resolved, with five documented PDF
  toolchain extras;
- `pip check`: no broken requirements;
- `pip-audit --skip-editable`: no known vulnerability in audited packages,
  with `torch==2.13.0+cpu` explicitly skipped because that local build is not
  represented on PyPI; and
- npm audit: zero vulnerabilities.

The live interface audit captured desktop and mobile states for the eight
primary routes plus paper, topic, and author detail views: 22 HTTP-200 captures
with zero console/page errors and zero horizontal-overflow findings. All route
captures, including segmented long pages, were visually inspected. This is a
Chromium-focused engineering/accessibility check, not a comprehensive browser,
assistive-technology, usability, or WCAG-conformance study.

## Full reproduction and release acceptance gate

The root delivery process must run these commands from a clean committed
candidate, using a fresh work directory:

```bash
scripts/reproduce_all.sh \
  --mode full \
  --source-db data/papers.db \
  --work-dir "tmp/reproduce/final-$(git rev-parse --short HEAD)"

(cd "tmp/reproduce/final-$(git rev-parse --short HEAD)" && \
  sha256sum -c REPRODUCTION_SHA256SUMS)

make release
```

The generated `reproduction_manifest.json` must report the exact candidate
commit/tree, clean source state, full mode, successful stages, and a verified
file inventory. Both the clean-source and reproduced-state release archives,
their adjacent checksums/manifests, and the embedded manifests must pass
`python -m app.reproducibility.release verify`. The final archive must exclude
PDFs, SQLite databases, extracted text/chunks/indexes, raw external XML,
interface screenshots, private prompts/review histories, secrets, model files,
backups, and absolute local paths. Only after those checks pass may the exact candidate be tagged and
pushed as the delivery.

Complete full-corpus reproduction requires separately authorized local PDFs,
the source database, and the pinned dense model cache. An unrestricted clone
cannot recreate those restricted inputs; the sanitized release instead carries
permitted code, configurations, manifests, and redistributable evidence.

## External-only decisions and calibrated conclusion

Repository work cannot supply a student ID, supervisor, official degree or
programme nomenclature, submission date, university declaration, official lab
expansion, REC/IRB determination, funding/conflict attestation, institutional
AI-use approval, rights-holder PDF redistribution permission, production
ownership/contact procedures, supervisor approval, or venue/PDF eXpress
credentials.

The evidence supports an implemented and offline-evaluated source-traceable
research-intelligence platform for one frozen laboratory corpus. It does not
support claims of a novel retrieval algorithm, validated human advisory
benefit, comprehensive expertise inference, factual correctness from runtime
grounding labels, production-scale capacity, public-deployment approval, or
broad external validity.
