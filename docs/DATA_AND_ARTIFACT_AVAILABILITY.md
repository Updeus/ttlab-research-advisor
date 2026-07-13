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
| Source code | FastAPI/React code, tests, build/evaluation scripts, resolved Python and npm locks | Tracked; included in sanitized release |
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
- a validated 17-stage performance artifact with 102 zero-failure timed/RSS
  samples plus a post-run exact-lock environment validation; and
- manuscript figure/table generators and evidence hashes.

The relevant directories are `data/evaluation/`, `artifacts/phase1/`,
`artifacts/phase2/`, `artifacts/phase3/qa/`, `artifacts/phase4/`,
`artifacts/phase6/external_sanity/`, `artifacts/phase6/performance/`, and
`artifacts/phase6/reproduction/`. The performance validator binds the raw
samples to the clean source commit, immutable corpus hash, complete stage list,
resolved environment, and zero-failure condition; it is not inferred from the
harness implementation.

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

The independent verifier rejects non-regular or non-canonical archive members,
payloads outside the single archive root, checksum inventory disagreement,
local paths/secrets/restricted binary types, and any disagreement between the
embedded manifest and the actual archive root, source commit/tree, payload
inventory, released sizes/hashes, redaction totals, or dependency-lock hashes.
Existing commit-named release outputs are never silently overwritten.

A standalone `make release` writes under `build/releases/`. The one-command
reproduction instead constructs the same clean-source bundle under
`tmp/reproduce/<mode>/artifacts/release_bundle/`, keeping run-local evidence
separate from repository-root delivery artifacts. After experiments and
manuscript builds, it creates a second, explicitly suffixed
`*-reproduced-*` bundle under `artifacts/reproduced_release_bundle/`; this is a
sanitized record of regenerated tracked outputs, not a clean-source claim.

JSON/JSONL fields containing source passages, generated text that may quote a
publication, absolute local paths, private prompt content, or other restricted
payload are replaced with hash-and-length records. IDs, labels, numeric metrics,
configurations, and provenance hashes remain available. The scanner rejects
unsafe archive paths, PDF files or PDF magic bytes, SQLite/index payloads,
environment/credential files, absolute local user paths, private keys, and
recognized bearer/API-token patterns.

## Current release state

Only a bundle built from the final clean, tagged source commit is authoritative.
The final closure therefore rebuilds from that exact commit, verifies the
adjacent SHA-256 and every archive member, and records the versioned path in the
closure report. Earlier local audit bundles are non-authoritative even when
their scans pass. The builder prepares `v0.1.0-remediation`; it does not itself
create a tag, publish the repository, or change visibility.

## Reproduction levels

- `make reproduce-quick` verifies distributable code and existing sanitized
  evidence, runs bounded engineering checks, builds manuscripts, preflights
  PDFs, and constructs a release from a clean detached source worktree. It
  cannot recreate or validate the restricted corpus-dependent experiments.
- `make reproduce` creates a clean detached worktree under
  `tmp/reproduce/full/source`, snapshots an authorized source database with
  SQLite's backup API, copies PDFs only into ignored runtime paths, requires
  the pinned dense model, rebuilds
  derived state, runs evaluations/tests/builds/preflight, and emits a local
  manifest. The manifest separately records the clean starting commit/tree and
  expected post-execution generated-output changes. The isolated database,
  extracted text, chunks, and indexes remain restricted and are not copied
  into the tarball.

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
