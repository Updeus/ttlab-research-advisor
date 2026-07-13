# Data and Artifact Availability

## Authorization and rights boundary

The user has stated that TTLAB explicitly authorized this project and use of
the laboratory corpus. That authorization supports the research-engineering
work described here. It does not itself establish research-ethics-board
approval, copyright ownership, permission to redistribute every third-party
publication, institutional approval of public deployment, or endorsement by
any publication author.

The repository therefore distinguishes source availability from experiment
auditability. Restricted source PDFs and full derived text remain local;
redistributable code, schemas, judgments, configurations, aggregates, and
hash-linked sanitized records can be bundled without exposing the papers.

## Availability classes

| Class | Examples | Repository/release treatment |
|---|---|---|
| Source code | FastAPI/React code, tests, build and evaluation scripts | Tracked; included in sanitized release |
| Redistributable metadata | paper IDs/titles/authors/source URLs where present, schemas | Tracked; allowlisted after field scan |
| Evaluation evidence | silver labels, rationales, source locators, per-case rankings, metrics, prompts without full text | Tracked; included or field-sanitized |
| Derived aggregate evidence | corpus counts, hashes, manifests, result summaries, figures | Tracked; included |
| Restricted source payload | PDFs, substantial extracted/chunk text, runtime SQLite DB, vector indexes | Local/ignored; excluded |
| Private operational content | questions/profile history, bearer tokens, private prompts containing full source passages, logs with content | Local/protected; excluded |
| Reacquirable open sanity input | Europe PMC CC BY XML | Raw cache ignored; manifest retains ID, license evidence, source URL, and hash |
| Compiled manuscripts | thesis and IEEE PDFs | Built separately; omitted from sanitized code/data tarball by policy |

## Committed evidence inventory

The evidence-backed snapshot comprises:

- Phase 1 corpus/index evidence for 134 catalogue records, 96 eligible papers,
  719 eligible chunks, 36 no-text/needs-review records, and two excluded
  metadata/PDF mismatches;
- a 50-case retrieval silver set and complete per-mode rankings, tuning,
  ablations, paired statistics, and error taxonomy;
- a 50-case claim/citation/answer-point QA review;
- 28 synthetic recommendation profiles with raw outputs and two review passes;
- a 60-paper topic/author silver evaluation and author identity audit;
- a sanitized 48-output generated-content review with event-chain evidence;
- a three-document Europe PMC external format-sanity manifest; and
- manuscript figure/table generators and evidence hashes.

The relevant directories are `data/evaluation/`, `artifacts/phase1/`,
`artifacts/phase2/`, `artifacts/phase3/qa/`, `artifacts/phase4/`, and
`artifacts/phase6/external_sanity/`. A full Phase 6 performance result is not
committed at this documentation snapshot and must not be inferred from the
benchmark implementation.

## Sanitized release construction

Build the allowlist-based bundle with:

```bash
make release
```

or:

```bash
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.release build \
  --version 0.1.0-remediation \
  --out-dir build/releases
```

The builder writes a deterministic tarball, adjacent archive checksum, and
manifest. Inside the archive, `SHA256SUMS` covers payload members and
`REPRODUCE.md` states the rights boundary. Sorted paths, normalized modes,
zeroed UID/GID, source-commit timestamp, and a zero gzip timestamp make builds
deterministic for the same source commit and evidence inputs.

JSON/JSONL fields containing source passages, generated text that may quote a
publication, absolute local paths, private prompt content, or other restricted
payload are replaced with hash-and-length records. IDs, labels, numeric metrics,
configurations, and provenance hashes remain available. The scanner rejects
unsafe archive paths, PDF files or PDF magic bytes, SQLite/index payloads,
environment/credential files, absolute local user paths, private keys, and
recognized bearer/API-token patterns.

## Current release state

A local bundle exists for source commit
`d0d84aa6101a28c2f189b599b114650ebcdd38fd`, but the documentation snapshot is
newer. That bundle is a provisional builder proof, not the final release for the
current branch. Final delivery requires rebuilding from the final clean commit,
verifying the adjacent SHA-256, scanning every member, and recording the final
path and prepared tag in the closure report. The builder prepares
`v0.1.0-remediation`; it does not create a tag, publish the repository, or
change visibility.

## Reproduction levels

- `make reproduce-quick` verifies distributable code and existing sanitized
  evidence, runs bounded engineering checks, builds manuscripts, preflights
  PDFs, and constructs a release. It cannot recreate or validate the restricted
  corpus-dependent experiments.
- `make reproduce` copies an authorized source database into
  `tmp/reproduce/full`, requires the referenced permitted PDFs and pinned dense
  model, rebuilds derived state, runs evaluations/tests/builds/preflight, and
  emits a local manifest. The isolated database, extracted text, chunks, and
  indexes remain restricted and are not copied into the tarball.

A recipient without lawful access to the source papers can audit the released
code, schemas, sanitized judgments, aggregate and raw rankings, configurations,
and hashes, but cannot recreate the exact full-text corpus. This is an explicit
reproducibility limitation, not an invitation to bypass source terms.

## Citation and reuse

The final repository commit and prepared release tag are the primary software
identifiers. Publication metadata and source locators remain attributable to
their original publications; inclusion in this project does not relicense
them. Before distributing a compiled manuscript or additional source text, the
author must check the target venue, institutional policy, and applicable source
licenses. External attestations are listed in
`docs/EXTERNAL_SUBMISSION_CHECKS.md`.
