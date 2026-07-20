# Independent peer-review readiness baseline

Audit type: AI-assisted independent audit; not human peer review.
Audit date: 2026-07-20 (America/La_Paz, UTC-04:00).
Repository: `https://github.com/Updeus/ttlab-research-advisor`.
Checkout: `/mnt/c/Users/jarod/Desktop/Projects/Advisor`

This file records observations reproduced from the checked-out repository. Older
status reports were treated as leads, not as current evidence.

## Git baseline

| Field | Reproduced value |
|---|---|
| Branch | `main` |
| Commit | `b561fa73c1de50569d7e76261b2aa37195524c21` |
| Commit subject | `Add scheduled TTLAB ingestion worker` |
| Upstream divergence | `HEAD...origin/main = 0/0` |
| Initial working tree | clean (`git status --short` returned no paths) |
| Audit mutation boundary | only `docs/peer_review_readiness/**` may be added |

The current commit adds a scheduled ingestion subsystem after the revision bound
into the tracked manuscript evidence. That revision distinction is material and
is addressed in `AUDIT_REPORT.md` and `CROSS_DOCUMENT_CONSISTENCY.md`.

## Host and toolchain

| Tool | Reproduced value |
|---|---|
| OS | Ubuntu 24.04.1 LTS under WSL2 |
| Kernel | `5.15.133.1-microsoft-standard-WSL2` x86_64 |
| Python | 3.12.3 |
| Node.js | v20.20.2 |
| npm | 10.8.2 |
| GNU Make | 4.3 |
| LaTeX engine used by the repository | Tectonic 0.16.9 (`/home/jarod/.local/bin/tectonic`) |
| Poppler/pdfinfo | 24.02.0 |
| qpdf | 11.9.0 |

`latexmk`, `pdflatex`, `xelatex`, and `lualatex` were not installed. These were
environment-discovery probes, not repository gate failures: the Makefile uses
Tectonic and both manuscripts compiled with it.

## Manuscript baseline

| Item | Reproduced value | Readiness interpretation |
|---|---:|---|
| IEEE paper | 8 Letter pages | fails the required maximum of 6 pages including references |
| Paper cited references | 29 `\\bibitem` entries | exceeds the requested approximate target of 20 |
| Shared BibTeX database | 32 entries | three entries are not cited by the paper |
| Thesis | 74 A4 pages | fails the required minimum of 75 pages |
| Thesis PDF structure | qpdf check passed; embedded fonts; no Type 3 fonts | engineering preflight only |
| Paper PDF structure | qpdf check passed; embedded fonts; no Type 3 fonts | engineering preflight only |
| PDF accessibility | both PDFs report `Tagged: no` | neither build establishes PDF/UA accessibility |
| Paper size | 261,672 bytes | informational |
| Thesis size | 835,873 bytes | informational |

Paper page 8 contains only references [19]-[29] in the left column and leaves the
right column blank. Page 6 is dominated by the full-width Evaluation Dashboard
screenshot. These rendered observations support a specific two-page compression
path; they do not justify removing negative results.

The thesis comprises 74 total pages. The audit counted 10 front-matter pages, 48
main-chapter pages, 11 appendix pages, and 5 bibliography pages. The literature
review is approximately three pages, which is the clearest substantive expansion
target. Page-count compliance must not be achieved with blank pages, spacing, or
duplicated metric prose.

## Required command results

All commands were invoked from the repository root unless shown otherwise.

| Command | Result | Reproduced details |
|---|---|---|
| `git status --short` | PASS | initially empty |
| `git rev-parse HEAD` | PASS | `b561fa73c1de50569d7e76261b2aa37195524c21` |
| `make paper` | PASS WITH WARNINGS | Tectonic completed; 8-page PDF; underfull-box warnings |
| `make thesis-assets-frozen` | PASS | frozen assets regenerated/validated |
| `make thesis-compile` | PASS WITH WARNINGS | Tectonic completed; 74-page PDF; underfull/font notices; intermediate chapter BibTeX errors were ignored |
| `make docs-validate` | PASS | 38 Markdown files and 25 local links initially; 44 tracked Markdown files and 25 local links after staging the six audit Markdown files |
| `PYTHONPATH=backend .venv/bin/python -m pytest` | PASS | 255 passed, 6 dependency deprecation warnings, 30.52 s |
| `cd frontend && npm run build` | PASS | Vite 6.4.3; 1,809 modules; 352.87 kB JS (102.68 kB gzip) |
| `npm --prefix frontend test` | PASS | 20 tests across 6 files |
| `npm --prefix frontend run test:e2e` | PASS | 6 Chromium tests |
| `npm --prefix frontend audit --audit-level=high` | PASS | 0 reported vulnerabilities |
| `.venv/bin/python scripts/validate_manuscripts.py` | PASS, BUT INVALID GATE | 38 sources, 30 floats, 81 citation occurrences, 32 BibTeX entries; validator accepts paper 6-8 pages and thesis 40-500 pages |
| `.venv/bin/python thesis/scripts/validate_word.py build/thesis-editable.docx` | PASS | editable derivative opened and validated |

The manuscript validator's PASS is not evidence of the user-specified page
constraints. `scripts/validate_manuscripts.py:171-193` explicitly accepts the
non-compliant 8-page paper and 74-page thesis.

None of the Phase 1 minimum commands in the table failed; the separate clean full
reproduction described below did fail. The following optional engine probes also
failed with `command not found`: `latexmk --version`, `pdflatex --version`,
`xelatex --version`, and `lualatex --version`. Tectonic was available and was the
configured engine, so those probe failures are environmental observations rather
than blocked builds.

## Database and corpus snapshot

The live SQLite file is `data/papers.db`.

| Item | Reproduced value |
|---|---|
| Database size | 17,256,448 bytes |
| Raw database SHA-256 | `dc33ad9c723c65725d6bb4e1c73b6e2d9f1a7edccd3d6e17dc2dfc6457029974` |
| SQLite quick check | `ok` |
| Foreign-key violations reported by explicit check | 0 |
| SQLite connection enforcement | `PRAGMA foreign_keys = 0` in the live default connection |
| Journal mode | `delete` |
| Papers | 134 |
| Authors | 136 |
| Topics | 39 |
| Raw chunks | 735 |
| Stored RAG answers | 27 |
| Stored recommendation runs | 7 |
| Generated paper artifacts | 14 |
| Review events | 48 |

Eligibility partition:

| Status | Papers |
|---|---:|
| `eligible` | 96 |
| `excluded_pdf_metadata_mismatch` | 2 |
| `needs_review` / no eligible text | 36 |

All 134 papers and all 39 topics have `review_status=needs_review` in the current
database. Technical corpus eligibility is therefore not equivalent to editorial
approval for anonymous public presentation.

Frozen corpus identity:

| Field | Value |
|---|---|
| Snapshot ID | `corpus-04a010207327069a` |
| Snapshot hash | `04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5` |
| Eligible papers | 96 |
| Eligible chunks | 719 |
| Excluded suspected title/PDF mismatches | 2 |
| Records without eligible text | 36 |
| Eligible chunks with `Unknown` section | 199 |
| OCR use in frozen corpus | 0 papers; optional path only |

## Index identifiers

| Artifact | Reproduced value |
|---|---|
| Feature-hashing dimensions | 256 |
| Feature-hashing payload SHA-256 | `f23353187252bb88188f8f5561c90de282481c1e87130405ccf556a14f319fa5` |
| Feature-hashing manifest SHA-256 | `deda47a440f6f36c70d35b4684058cb0b11d5473aba5ac97c5192ca89f5b03c5` |
| Learned-dense dimensions | 384 |
| Dense model | `sentence-transformers/all-MiniLM-L6-v2` |
| Dense revision | `826711e54e001c83835913827a843d8dd0a1def9` |
| Dense payload SHA-256 | `ac0d1242787760638f294d8268166a99782d652fef66af70c5ba3739e1b15673` |
| Dense manifest SHA-256 | `203b6b28ff62d2fa3abad47e243890e66bf25aa14904a3f6bf764d5878a45886` |
| Indexed eligible chunks | 719/719 in keyword, feature-hashing, and dense representations |
| Index-manifest code commit | `166c6fc45befa0a2847b320328042ab861a34e9d` |

The freshly rebuilt dense payload had a different whole-file hash because the
build ID and timestamp changed, but its ordered `(chunk_id, source_hash,
embedding)` record hash matched the tracked payload exactly:
`598d115e8bc8dde8d4caaed70704f2fa68f65faaea9413baff4344655f68bc62`.
This confirms deterministic vector records for the observed rebuild; it does not
make the old manifest's code-commit field current.

Feature hashing is a signed lexical feature baseline. It is not a learned
semantic encoder. API aliases that still call it `semantic` are audited as a
terminology defect.

## Current evidence and experiment artifacts

The repository contains executed artifacts for:

- Phase 1 corpus/extraction/section/index evidence;
- Phase 2 retrieval runs, raw rankings, tuning, ablations, bootstrap intervals,
  paired tests, and error taxonomy;
- Phase 3 offline-extractive QA, atomic claim/citation labels, metrics, and error
  records;
- Phase 4 recommendation proxy review, weight sensitivity, topic/author/identity
  review, and generated-output review;
- Phase 6 performance validation and the three-document Europe PMC JATS/XML
  format sanity check;
- release scanning, dependency lock checks, interface tests, and manuscript
  generation.

Key reproduced evidence boundaries:

| Result family | Current recorded result | Important boundary |
|---|---|---|
| Retrieval | keyword held-out MRR 0.947; dense 0.939; tuned hybrid 0.860 | 20-case test; AI-reviewed silver; no corrected hybrid superiority |
| QA | claim support 0.995; citation correctness 0.625; answer-point coverage 0.136 | 50 cases; offline extractive; same declared AI review process |
| Abstention | 0/4 unanswerable QA cases abstained | direct negative result |
| Finder | relevance delta 0.024; 95% CI [-0.024, 0.071] | 28 synthetic profiles; no demonstrated uplift |
| Finder feasibility | 84/84 full-finder items judged partial; 0 strict passes | no supervisor/student feasibility validation |
| Topics | lexical P/R/F1 0.652/0.484/0.556; dense 0.417/0.694/0.521 | 24 held-out papers; sparse per-label support |
| Section labels | exact accuracy 0.900 on 40 AI-silver cases | zero Abstract cases; 199 eligible chunks remain `Unknown` |
| Performance | 17 stages, 102 samples, 0 failures | commit `5ccf22ec...`; one WSL2 host; concurrency one |
| External format | 3/3 lexical top-one matches | three CC BY JATS/XML articles; not PDF or quality validation |

Provenance caveats reproduced from the files:

- `thesis/generated/evidence_snapshot.json`,
  `manuscript_metrics_manifest.json`, and `runtime_probe.json` bind a committed
  base of `f4abb767018f9db13a2a9ac5bee1e6f6fca3428e`, not current HEAD.
- the committed performance artifact names source commit
  `5ccf22ec39cb33bf179cdff6954bfc9e0ce8dbc4`;
- both tracked QA execution manifests say `working_tree_dirty: true`;
- the Phase 1 evidence records commit `1f31dc1...` with a materially dirty tree;
- the pre-audit checkout contained no completed top-level exact-HEAD
  `reproduction_manifest.json` plus `REPRODUCTION_SHA256SUMS`;
- the only existing root release bundle before this audit was for an older
  commit (`d0d84aa...`).

## Exact-HEAD full reproduction audit run

Command started from the clean checkout:

```bash
./scripts/reproduce_all.sh \
  --mode full \
  --work-dir /tmp/ttlab-peer-audit-b561fa \
  --source-db data/papers.db
```

Outcome: **FAIL (exit 1; repository-caused)** after approximately 32 minutes.
The clean detached source copy reached the `performance-full` stage, whose exact
command was:

```bash
/mnt/c/Users/jarod/Desktop/Projects/Advisor/.venv/bin/python \
  -m app.evaluation.performance_benchmark \
  --profile full \
  --repetitions 3 \
  --database /tmp/ttlab-peer-audit-b561fa/source/data/papers.db \
  --runtime-root /tmp/ttlab-peer-audit-b561fa/source \
  --out /tmp/ttlab-peer-audit-b561fa/artifacts/performance/performance_full_results.json
```

The benchmark completed its 17 named stages but recorded 40 failed samples: six
each in feature-hashing retrieval, dense retrieval, hybrid retrieval, offline
answering, offline recommendation, and ASGI API probes, plus four browser-page
probes. The shared error was `Database embedding statuses disagree with the
manifest for 719 chunk(s).` The run-local database contained 735/735 chunks with
`embedding_status=not_indexed`.

This is caused by `scripts/reproduce_all.sh:153-156`, which deliberately passes
`--no-status-update` while building both authoritative vector indexes, followed
by consumers that require the database status and manifests to agree. The index
payloads/manifests existed; the database half of the state contract did not.
Because `performance-full` returned non-zero, its validator, manuscript rebuild,
final reproduction manifest/checksums, and current release build were not run.
The transient log and result hashes were respectively
`4b571e92924915a2c3425ee3c44332ffb5f3ba88b50fbda24bb9ebe588713262`
and `8c1223ac03746824ac32bf739030ee16890d09643653a75877e899f56c01691d`.
This clean-current failure is REPRO-003; it is not an unavailable-service or
machine-capacity failure.

One already reproduced pipeline defect is independent of the final outcome:
`scripts/reproduce_all.sh:141-150` runs the named PDF identity audit before the
run-local extraction files exist, so its log reported 98 `not_assessed` records.
Fresh overwrite extraction subsequently repaired the partition to 96 matched, 2
possible mismatches, and 36 records without PDFs before building 719 eligible
chunks. The early audit log is therefore not identity evidence even though the
later extraction was independently derived.

## Baseline conclusion

The repository is highly buildable and unusually explicit about negative
results. Those strengths do not satisfy formal readiness. At this baseline, the
paper and thesis fail their hard page constraints; the most important RAG and
Finder evidence is materially negative; anonymous public data is not editorially
approved; the current system revision is newer than the tracked manuscript
evidence; and clean exact-candidate reproduction fails before its final
manifest/checksums and current release can be produced.
