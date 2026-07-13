# Reproducibility Checklist

The narrative protocol and current evidence status are maintained in
[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md). This checklist remains the concise
operator sequence.

This checklist distinguishes a distributable verification run from the
authorized full-corpus experiment. The earlier 25-record demo launcher remains
useful for product demonstration, but it is not the research reproduction
entry point and its output must not support full-corpus claims.

## 1. Obtain source and prerequisites

```bash
git clone https://github.com/Updeus/ttlab-research-advisor.git
cd ttlab-research-advisor
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt \
  -r backend/requirements-dense.txt -r backend/requirements-ocr.txt
npm --prefix frontend ci
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
release construction, and a hash manifest. It does not recreate or claim the
restricted full corpus.

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

1. dependency/version checks;
2. disposable DB copy, seed upsert, author repair, and PDF identity audit;
3. full PDF extraction and deterministic chunking;
4. complete keyword, feature-hashing, and learned-dense indexes;
5. retrieval, QA-label, recommendation-proxy, topic/author, external-sanity,
   and performance evaluation gates;
6. backend/frontend/unit/E2E builds and tests;
7. paper/thesis compilation and PDF preflight/page rendering;
8. sanitized release creation and archive scan;
9. a final file-level SHA-256 reproduction manifest.

The working database, extracted text, chunks, and indexes remain under
`tmp/reproduce/full` and are labeled restricted runtime payloads in the local
manifest. They are never inserted into the release archive.

## 5. Inspect outputs

- Reproduction workspace: `tmp/reproduce/<mode>/`
- Command logs: `tmp/reproduce/<mode>/logs/`
- Local run manifest: `tmp/reproduce/<mode>/reproduction_manifest.json`
- Sanitized tarball and adjacent manifest/checksum: `build/releases/`
- Committed performance evidence: `artifacts/phase6/performance/`
- External sanity evidence: `artifacts/phase6/external_sanity/`

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
