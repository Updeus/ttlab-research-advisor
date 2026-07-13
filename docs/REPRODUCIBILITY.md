# Reproducibility Guide

## Reproducibility claim

The project supports two different claims:

- **distributable verification** checks code, committed sanitized evidence,
  tests, frontend builds, document builds/preflight, and release sanitization;
- **full-corpus reproduction** rebuilds corpus-dependent state and experiments
  only when the operator separately possesses the authorized database, PDFs,
  and pinned dense-model snapshot.

The sanitized release deliberately cannot recreate restricted full text. This
limits independent end-to-end reproduction but prevents reproducibility from
being used as a pretext to redistribute source material without evidence of
permission.

## Pinned software and system prerequisites

Create an isolated environment from the tracked requirements:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt \
  -r backend/requirements-dense.txt \
  -r backend/requirements-ocr.txt
npm --prefix frontend ci
```

Core Python packages are exactly pinned, including FastAPI 0.139.0, Starlette
1.3.1, SQLModel 0.0.22, PyMuPDF 1.25.1, pytest 9.1.1, and httpx 0.28.1. Dense
extras pin sentence-transformers 5.6.0, Transformers 5.13.1, Hugging Face Hub
1.23.0, and CPU PyTorch 2.13.0. The frontend lock file is authoritative for npm
packages.

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
`scripts/reproduce_all.sh --mode full`, copies authorized state into an
isolated workspace, and runs the full pipeline. `make release` constructs and
scans the sanitized archive without publishing it or creating a Git tag.

Equivalent explicit invocation:

```bash
scripts/reproduce_all.sh \
  --mode full \
  --source-db /permitted/path/papers.db \
  --work-dir tmp/reproduce/full
```

The script is fail-loud: missing tools, database, local PDFs, model snapshot,
test/build failure, visible manuscript placeholders, PDF structural failure,
page-render mismatch, or release-scan finding ends the run with nonzero status.

## Full isolated pipeline

The full path performs these operations in order:

1. records dependency/runtime availability;
2. copies the source database and upserts permitted seed metadata;
3. repairs known author-parser artifacts and audits PDF/title identity;
4. re-extracts PDFs and deterministically re-chunks text;
5. rebuilds keyword, 256-dimensional feature-hashing, and pinned 384-dimensional
   dense indexes into the isolated workspace;
6. validates/runs retrieval, QA, recommendation, topic/author, generated-output,
   external-sanity, and performance workstreams;
7. runs backend tests and frontend unit, accessibility, build, and end-to-end
   checks;
8. compiles the IEEE paper and thesis;
9. checks PDF structure, metadata, fonts, text markers, and rendered page counts;
10. builds/scans the sanitized release; and
11. emits a file-level SHA-256 reproduction manifest.

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
  zero gzip timestamp, `SHA256SUMS`, and an adjacent archive checksum.

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

At this documentation snapshot, no committed full performance result exists,
and no complete `tmp/reproduce/full/reproduction_manifest.json` is present.
Accordingly, performance and full one-command reproduction remain unproven
gates. A local release bundle from commit `d0d84aa6101a...` demonstrates the
builder, but it predates the current documentation/evidence commit and must be
rebuilt for final delivery.

## Inspecting outputs

After a successful run, inspect:

```text
tmp/reproduce/<mode>/logs/
tmp/reproduce/<mode>/artifacts/
tmp/reproduce/<mode>/reproduction_manifest.json
build/releases/*.tar.gz
build/releases/*.manifest.json
build/releases/*.sha256
build/ieee-paper.pdf
build/thesis.pdf
```

For the release archive, verify the adjacent SHA-256, run the release verifier,
and inspect the allowlist/field-sanitization counts in the manifest:

```bash
sha256sum -c build/releases/<archive>.sha256
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.release verify \
  build/releases/<archive>.tar.gz
```

Automated PDF page rendering proves that every page can be rasterized; it does
not prove readable layout. Final delivery still requires visual inspection of
every rendered page and primary frontend route.

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
