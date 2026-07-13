# Reproducibility Guide

## Reproducibility claim

The project supports two different claims:

- **distributable verification** checks code, committed sanitized evidence,
  tests, frontend builds, document builds/preflight, and release sanitization;
- **full-corpus reproduction** rebuilds corpus-dependent state and experiments
  only when the operator separately possesses the authorized database, PDFs,
  and pinned dense-model snapshot.

The governing question is: **To what extent is the bounded artefact
reproducible and reviewable on documented local hardware, externally
format-compatible, and governed by privacy-minimizing, authenticated,
accessible evidence interfaces without redistributing restricted PDFs?**

The sanitized release deliberately cannot recreate restricted full text. This
limits independent end-to-end reproduction but prevents reproducibility from
being used as a pretext to redistribute source material without evidence of
permission.

## Pinned software and system prerequisites

Create an isolated environment from the tracked requirements:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
npm --prefix frontend ci
frontend/node_modules/.bin/playwright install chromium
```

`backend/requirements-lock.txt` is the resolved Python 3.12 lock for the app,
dense, OCR, test, and `pip-audit` paths; `backend/requirements-repro.in` is its
reviewable input. The lock includes exact versions for FastAPI 0.139.0,
Starlette 1.3.1, SQLModel 0.0.22, PyMuPDF 1.25.1, sentence-transformers 5.6.0,
Transformers 5.13.1, Hugging Face Hub 1.23.0, and CPU PyTorch 2.13.0. The
frontend lock file is authoritative for npm packages. Performance and
reproduction manifests record both lock-file SHA-256 values and the resolved
environment.

System tools required by the full command are Git, Node/npm, Tectonic, qpdf,
and Poppler (`pdfinfo`, `pdffonts`, `pdftotext`, `pdftoppm`). Tesseract is
needed only if an authorized input triggers OCR; the frozen corpus used no OCR.
Chromium must be installed for Playwright. Dependency installation is an
operator action and may require network access.

Acquire the exact dense model explicitly rather than allowing ordinary search
to download it:

```bash
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder acquire-dense-model
```

The required model is `sentence-transformers/all-MiniLM-L6-v2` revision
`826711e54e001c83835913827a843d8dd0a1def9`. The executed snapshot's model
artifact hash is
`18309e334c0231266dcaba3f9b70f47e919b787190a3e5d22744b240048c0a7c`.

## One-command entry points

```bash
make reproduce-quick
make reproduce
make release
```

`make reproduce-quick` runs the distributable verification path. It does not
recreate or validate corpus-dependent metrics. `make reproduce` invokes
`scripts/reproduce_all.sh --mode full`, creates a detached clean Git worktree,
copies authorized state into its ignored runtime paths, and runs the full
pipeline. `make release` constructs and scans a sanitized archive in
`build/releases/` without publishing it or creating a Git tag. Passing
`--install` to the script creates an isolated environment under the run
workspace and installs the tracked Python/npm locks.

Equivalent explicit invocation:

```bash
scripts/reproduce_all.sh \
  --mode full \
  --source-db /permitted/path/papers.db \
  --work-dir tmp/reproduce/full
```

The script is fail-loud: a lock mismatch, dependency/security finding at the
configured severity, missing tools/database/PDF/model, benchmark stage failure,
test/build failure, visible manuscript placeholder, PDF structural failure,
page-render mismatch, checksum mismatch, or release-scan finding ends the run
with nonzero status.

## Full isolated pipeline

The full path performs these operations in order:

1. creates a clean detached source snapshot and validates resolved dependency
   locks, package integrity, and security audits;
2. builds and verifies the sanitized release from that still-clean snapshot;
3. runs the external format sanity check and engineering test/build/E2E gates;
4. copies the source database, upserts permitted metadata, repairs known author
   artifacts, and audits PDF/title identity; the database copy uses SQLite's
   online backup API, rejects source drift, and records integrity/table counts;
5. re-extracts PDFs and deterministically re-chunks text;
6. rebuilds keyword, 256-dimensional feature-hashing, and pinned 384-dimensional
   dense indexes into the isolated workspace;
7. runs and independently validates the three-cold/three-warm performance
   profile before any generated evidence dirties the source snapshot, then
   copies only the validated result and validation record to their canonical
   Phase 6 paths;
8. validates/runs retrieval, QA, recommendation, topic/author, and
   generated-output workstreams;
9. compiles the IEEE paper and thesis;
10. checks PDF structure, metadata, fonts, text markers, and rendered page
    counts; and
11. builds a separately named post-experiment sanitized bundle from the
    generated state; and
12. emits and immediately verifies an exact file-level SHA-256 reproduction
    manifest. No log or other output file is created after this final hash gate.

Runtime writes stay below `tmp/reproduce/<mode>/`. The live database and
authoritative indexes are not overwritten by the benchmark or bounded demo.
Answer/recommendation probes set persistence off where supported.

## Determinism and provenance controls

- Corpus identity is derived from the ordered eligible chunk IDs and source
  hashes, not row counts alone.
- Index manifests store snapshot ID/hash, model/provider identity, exact model
  revision/artifact hash, dimensions, normalization, configuration hash,
  creation time, code commit, and index checksum.
- Index writes are atomic. A partial/demo index is isolated and cannot set the
  authoritative completeness status.
- Retrieval evaluation stores the question-set hash, candidate-pool controls,
  development/test split, weight search, selected configuration, per-query
  rankings, bootstrap seeds, and paired statistics.
- QA, recommendation, topic, and generated-output evaluations retain reviewer
  identity/type, pass order/seeds, raw decisions, corrections, and file hashes.
- The release uses sorted paths, normalized metadata, the source commit time,
  zero gzip timestamp, `SHA256SUMS`, and an adjacent archive checksum. Its
  verifier rejects non-regular/unsafe members and cross-checks the embedded
  manifest's root, source commit/tree, file inventory, per-file hashes/sizes,
  redaction counts, and dependency-lock hashes against the archive bytes.
- The benchmark writes an atomic `status: in_progress` checkpoint after each
  completed stage. `--resume` is allowed only when source, corpus,
  configuration, hardware, resolved packages, and lock provenance match
  exactly. The independent validator requires all 17 stages, three cold and
  three warm samples per stage, zero failed samples, clean start/end source
  provenance, and path-independent commands.
- The reproduction manifest distinguishes the clean detached commit/tree at
  start from expected generated-output changes in the disposable worktree.
- Authorized SQLite state is transferred with `sqlite3.Connection.backup`,
  source before/after drift checks, target integrity checks, core-table counts,
  and no-overwrite publication. The executed benchmark snapshot record is
  `artifacts/phase6/reproduction/database_snapshot_validation.json`.

Timestamp fields and live network timing are intentionally not bit-for-bit
deterministic. Remote discovery/acquisition, OS scheduling/cache state, and
hardware can change latency. These sources of variation are retained in
manifests rather than normalized into false equivalence.

## Expected evidence and current status

Committed, executed evidence currently exists for:

- Phase 1 corpus/index integrity;
- Phase 2 retrieval baselines, tuning, sensitivity, ablations, statistics, and
  failures;
- Phase 3 QA claim/citation review and the unavailable Ollama record;
- Phase 4 recommendation, topic/author, and generated-output review; and
- Phase 6 three-document Europe PMC sanity acquisition/check.

The full performance gate is closed by the validated 17-stage,
three-cold/three-warm artifact at
`artifacts/phase6/performance/performance_full_results.json`: 102 samples and
102 RSS records passed with zero failures from clean source commit `5ccf22e`.
The post-run environment record at
`artifacts/phase6/reproduction/python_environment_validation.json` confirms
every one of the 92 exact Python pins. The measured environment had 96 packages;
the final locked environment has 97, differing only by the subsequently added
`pytesseract==0.3.13`. OCR remained explicitly not applicable in the measured
zero-OCR corpus.

Full one-command reproduction and the final clean release are post-commit
acceptance gates, not facts inferred from the scripts. Final delivery is valid
only when the exact final commit produces
`tmp/reproduce/full/reproduction_manifest.json`, passes its checksum inventory,
and yields a clean-source archive whose adjacent manifest/checksum and embedded
manifest all verify. Those executed outputs, rather than an earlier local audit
bundle, are authoritative.

The current standalone manuscript outputs are `build/ieee-paper.pdf` at 8
Letter pages and `build/thesis.pdf` at 74 A4 pages. Their availability closes
the earlier manuscript-drafting gap; exact-final-commit acceptance separately
rebuilds and preflights both PDFs.

## Inspecting outputs

After a successful run, inspect:

```text
tmp/reproduce/<mode>/logs/
tmp/reproduce/<mode>/artifacts/
tmp/reproduce/<mode>/reproduction_manifest.json
tmp/reproduce/<mode>/REPRODUCTION_SHA256SUMS
tmp/reproduce/<mode>/artifacts/release_bundle/*.tar.gz
tmp/reproduce/<mode>/artifacts/release_bundle/*.manifest.json
tmp/reproduce/<mode>/artifacts/release_bundle/*.sha256
tmp/reproduce/<mode>/artifacts/reproduced_release_bundle/*.tar.gz
tmp/reproduce/<mode>/artifacts/reproduced_release_bundle/*.manifest.json
tmp/reproduce/<mode>/artifacts/reproduced_release_bundle/*.sha256
tmp/reproduce/<mode>/source/build/ieee-paper.pdf
tmp/reproduce/<mode>/source/build/thesis.pdf
```

These are reproduction-workspace paths. A standalone `make release` instead
writes `build/releases/`, while standalone `make thesis` and `make paper` write
the repository-root `build/` directory.

For the release archive, verify the adjacent SHA-256, run the release verifier,
and inspect the allowlist/field-sanitization counts in the manifest:

```bash
(cd tmp/reproduce/<mode>/artifacts/release_bundle && \
  sha256sum -c <archive>.sha256)
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.release verify \
  tmp/reproduce/<mode>/artifacts/release_bundle/<archive>.tar.gz
```

Automated PDF page rendering proves that every page can be rasterized; it does
not prove readable layout. Acceptance therefore includes a recorded visual
inspection of every rendered page and primary frontend route; the automated
gate alone must not be described as that inspection.

## Non-reproducible and external-only elements

- Exact full-corpus reruns require lawful access to third-party PDFs.
- The AI runtime did not expose a public immutable model tag/digest for the
  Codex reviewer, so none is inferred.
- The Ollama service was unavailable during the recorded QA comparison.
- No human-participant study, usability score, advisory benefit, supervisor
  endorsement, or institutional ethics determination is reproduced because no
  such study/evidence exists.
- IEEE PDF eXpress requires venue credentials and cannot be replaced by local
  preflight.

See `docs/DATA_AND_ARTIFACT_AVAILABILITY.md` for the release boundary and
`docs/EXTERNAL_SUBMISSION_CHECKS.md` for author/institution/venue attestations.
