# Pre-remediation baseline

Captured on 2026-07-12 before any application-behaviour change on
`codex/fix-audit-and-finalize-paper`. The code baseline is `origin/main` at
`ce6d805afba27c2550da2ca58d1f844793ea25a8`; branch HEAD additionally contains
only the committed master remediation prompt at `6492445`.

## Executed gates

| Gate | Result | Raw log |
|---|---:|---|
| Backend tests | 71 passed, 5 warnings | `backend-tests.log` |
| Frontend clean install | passed; npm reported 0 vulnerabilities | `frontend-npm-ci.log` |
| Frontend production build | passed; 1,796 modules transformed | `frontend-build.log` |
| Backend smoke check | 16 pass, 0 warn, 0 fail | `backend-smoke.log` |
| Evidence collection | passed | `evidence-collection.log` |
| Disposable runtime probe | passed | `runtime-probe.log` |
| IEEE paper build | passed with one underfull-box warning | `paper-build.log` |
| Thesis build | passed with warnings, including one 0.46 pt overfull box | `thesis-build.log` |
| Paper PDF structure/fonts | qpdf passed; fonts embedded; no Type 3; metadata absent | `qpdf-paper.log`, `pdffonts-paper.log`, `pdfinfo-paper.log` |
| Thesis PDF structure/fonts | qpdf passed; fonts embedded; no Type 3; incomplete metadata | `qpdf-thesis.log`, `pdffonts-thesis.log`, `pdfinfo-thesis.log` |

Passing engineering gates do not establish retrieval, answer, recommendation,
topic, or author quality. The baseline evaluation files are placeholders or
missing and are explicitly excluded from effectiveness claims.

## Reproduced audit defects

- SQLite contains 134 papers, 98 extracted PDFs, 698 pages, 756 chunks, 126
  author strings, 39 topics, 27 saved answers, 7 recommendation runs, 14 paper
  artefacts, and no review events.
- SQLite FTS contains all 756 chunks, but the active feature-hashing JSON has
  only 25 records. SQLite simultaneously reports 300 chunks as
  `indexed:hashing`, proving stale status.
- Thirty-five papers have no PDF and one has `download_failed` status.
- 249 of 756 chunks have an `Unknown` section label.
- Every paper, author, topic, answer, recommendation, and artefact requiring
  review remains `needs_review`; no AI or human review event exists.
- The smoke check incorrectly calls the 25-record hashing file a passing
  “semantic index”; this is preserved as baseline evidence, not endorsed.
- The built conference paper is three US-Letter pages and has no PDF title,
  author, subject, or keywords. The thesis is 66 A4 pages and has title/subject
  only. Both are untagged, not linearized, and contain unresolved manuscript
  problems documented in the remediation matrix.

## Artefact policy

`pre-change-manifest.json` records counts, statuses, relative paths, sizes, and
SHA-256 hashes. `backup-manifest.json` proves that the runtime database and
index were copied and checksum-verified under the gitignored
`private-backups/` directory. Restricted database/index bytes are deliberately
not committed.
