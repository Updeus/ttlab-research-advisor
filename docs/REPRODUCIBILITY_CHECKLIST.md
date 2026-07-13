# Reproducibility Checklist

The narrative protocol and current evidence status are maintained in
[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md). This checklist remains the concise
operator sequence.

The committed performance evidence has passed its full-profile validator (17
stages, 102 samples/RSS records, zero failures). The exact final commit is
accepted only after this checklist's full one-command run and clean-release
verification pass; the scripts alone are not completion evidence.

The current standalone manuscript outputs are an 8-Letter-page IEEEtran paper
and a 74-A4-page thesis. They are available now; the full run below rebuilds and
preflights both PDFs so their presence is not mistaken for proof that the
exact-final-commit gate has passed.

This checklist distinguishes a distributable verification run from the
authorized full-corpus experiment. The earlier 25-record demo launcher remains
useful for product demonstration, but it is not the research reproduction
entry point and its output must not support full-corpus claims.

## 1. Obtain source and prerequisites

```bash
git clone https://github.com/Updeus/ttlab-research-advisor.git
cd ttlab-research-advisor
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
npm --prefix frontend ci
frontend/node_modules/.bin/playwright install chromium
```

Required system tools are Git, Node/npm, Tectonic, Poppler (`pdfinfo`,
`pdffonts`, `pdftotext`, `pdftoppm`), and qpdf. Tesseract is needed only when an
authorized corpus actually triggers OCR. The frozen TTLAB snapshot used no OCR.

## 2. Verify distributable material

```bash
make reproduce-quick
```

This fail-loud command runs dependency probes, the official Europe PMC CC BY
sanity acquisition, backend/frontend/unit/E2E tests, a bounded benchmark,
paper/thesis builds, PDF structural/font/text/page-render preflight, sanitized
release construction from a clean detached source snapshot, and a hash
manifest. It does not recreate or claim the restricted full corpus. Use
`scripts/reproduce_all.sh --mode quick --install --work-dir <fresh-path>` to
create an isolated locked environment as part of the run.

## 3. Supply authorized full-corpus inputs

Full reproduction additionally requires:

- `data/papers.db`, the authorized local source snapshot;
- the local PDFs referenced by that DB under `data/pdfs/`;
- the pinned `sentence-transformers/all-MiniLM-L6-v2` model revision already in
  the Hugging Face cache.

Do not copy these inputs from the sanitized release: they are deliberately not
there. Obtain them only through a permitted institutional or publisher path.

## 4. Run the full isolated reproduction

```bash
make reproduce
```

Or select paths explicitly:

```bash
scripts/reproduce_all.sh \
  --mode full \
  --source-db /permitted/path/papers.db \
  --work-dir tmp/reproduce/full
```

The command performs, in order:

1. clean detached source snapshot, dependency-lock validation, package
   integrity, and security audits;
2. clean-source sanitized release construction and independent archive scan;
3. external sanity plus backend/frontend/unit/E2E gates;
4. integrity-checked SQLite backup with source-drift rejection, seed upsert,
   author repair, PDF identity audit, full extraction, and deterministic
   chunking;
5. complete keyword, feature-hashing, and learned-dense indexes;
6. strict three-cold/three-warm performance benchmark and independent
   zero-failure validator;
7. retrieval, QA-label, recommendation-proxy, topic/author, and persisted-output
   evaluation gates;
8. paper/thesis compilation and PDF preflight/page rendering; and
9. a separately named post-experiment sanitized release; and
10. a final exact file-level SHA-256 reproduction manifest and checksum
    verification, with no subsequently created log file.

The working database, extracted text, chunks, and indexes remain under
`tmp/reproduce/full` and are labeled restricted runtime payloads in the local
manifest. They are never inserted into the release archive.

## 5. Inspect outputs

- Reproduction workspace: `tmp/reproduce/<mode>/`
- Command logs: `tmp/reproduce/<mode>/logs/`
- Local run manifest: `tmp/reproduce/<mode>/reproduction_manifest.json`
- Reproduction release tarball/manifest/checksum:
  `tmp/reproduce/<mode>/artifacts/release_bundle/`
- Post-experiment sanitized tarball/manifest/checksum:
  `tmp/reproduce/<mode>/artifacts/reproduced_release_bundle/`
- Standalone `make release` output: `build/releases/`
- Committed performance evidence: `artifacts/phase6/performance/`
- External sanity evidence: `artifacts/phase6/external_sanity/`
- Reproduction-built PDFs: `tmp/reproduce/<mode>/source/build/`

Review every final PDF page visually after the automated rendered-page gate.
Automated page generation proves renderability, not human-readable layout.

## 6. Failures and non-claims

- A missing authorized DB/PDF/model is an explicit full-reproduction blocker;
  the script exits rather than generating partial metrics.
- A network failure remains in the discovery/external acquisition record and
  is not converted into success.
- A quick run is not full-corpus evidence.
- Test/build success is engineering evidence, not retrieval, recommendation,
  answer-quality, usability, or external-validity evidence.
- No tag is created and no repository visibility changes automatically.
