# Phase 1 Corpus and Index Integrity Report

> **Archived Phase 1 execution record.** The values in this report are bound to
> `corpus-04a010207327069a` and are retained as audit-baseline evidence. They
> must not be read as the current manuscript snapshot. Post-remediation v1-form
> and v2 evidence use `corpus-f4638c633bea82b0`; current delivery boundaries are
> summarized in `docs/peer_review_readiness/FINAL_READINESS_REPORT.md`.

## Scope and evidence boundary

This report records the executed Phase 1 state after metadata repair, PDF/title
identity checks, conservative section reclassification, and complete index
rebuilds. It is an engineering and AI-assisted silver-review record, not a
human quality study. The machine-readable source is
`artifacts/phase1/phase1_evidence.json`; runtime database, PDF, extracted-text,
and vector bytes remain excluded from version control.

## Frozen corpus snapshot

- Catalogue records: **134**.
- Locally extracted PDFs: **98**.
- Eligible papers: **96**.
- Eligible chunks: **719**.
- Raw chunks: **735**.
- Excluded metadata/PDF mismatches: **2 papers and 16 chunks**.
- Records awaiting a usable PDF: **36**.
- Corpus snapshot ID: `corpus-04a010207327069a`.
- Corpus snapshot SHA-256:
  `04a010207327069a84d112b2aa065adb388e0ee7c129ba514db465057f22fbb5`.

The excluded records are:

1. `vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8`,
   whose stored PDF is *Soft-Churn: Optimal Switching between Prepaid Data
   Subscriptions on E-SIM support Smartphones*; and
2. `pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f`,
   whose stored PDF is *A Consumer Focused Open Data Platform*.

They remain visible as catalogue records but are not indexed or used as source
evidence. The intended documents have not been substituted or invented.

PDF unavailability is classified as 34 `no_pdf_url`, one `not_found`, and one
`network_error`. No authentication, paywall, or robots restriction was
bypassed. The 98 extracted documents comprise 75 mixed-content and 23 textual
files. The current corpus did not trigger OCR; all 134 records therefore report
`not_requested`. OCR support is optional and is covered by synthetic scanned,
blank, mixed-content, dependency-missing, and failure tests rather than a claim
of measured corpus OCR accuracy.

## Metadata and identity state

The source-backed repair recovered the malformed author lists and removed
`Click to View` from active authorship. The database contains 133 unresolved
active identities, two punctuation-only aliases merged into canonical records,
one invalid navigation-text record retained for audit history, and 133 alias
rows. Initials are not guessed to be full names. Canonical expertise summaries
are limited to evidence from indexed publications and do not imply availability,
endorsement, or supervisor suitability.

Verified DOI, abstract, and keyword values remain absent; they are not filled
from model guesses. Venue values are present for 128 records. Field-level
provenance and review state preserve this missingness explicitly.

## Section-label review

The section classifier was evaluated against a 40-chunk stratified,
source-inspected silver set prepared and verified in two fixed-seed AI-review
passes by `codex-ai-review`. The sample includes front matter, section
boundaries, and section interiors. It is not a human gold standard.

| Measure | Result |
|---|---:|
| Exact accuracy | 0.9000 (36/40) |
| Accuracy on non-`Unknown` expected labels | 0.8889 (32/36) |
| Macro precision | 0.8917 |
| Macro recall | 0.9040 |
| Expected `Unknown` rate | 0.1000 |
| Predicted `Unknown` rate | 0.1250 |

The four disagreements are retained rather than tuned away: three are mixed
section-boundary chunks and one uses a domain-specific heading that cannot be
safely mapped to the controlled section labels. Across the eligible corpus,
199 of 719 chunks remain `Unknown`; uncertainty is therefore visible rather
than replaced by a forced label.

## Authoritative retrieval indexes

All three retrieval representations cover the same ordered set of 719 eligible
chunk IDs and source hashes. SQLite `embedding_status` is a derived diagnostic;
the checksummed manifests are authoritative.

| Representation | Provider/model | Dimension | Coverage | Status |
|---|---|---:|---:|---|
| Keyword | SQLite FTS5 BM25 | n/a | 719/719 | complete |
| Lexical feature vector | `sha256-signed-token-hashing-v1` revision 1 | 256 | 719/719 | complete |
| Learned dense | `sentence-transformers/all-MiniLM-L6-v2` | 384 | 719/719 | complete |

The dense model is pinned to Hugging Face revision
`826711e54e001c83835913827a843d8dd0a1def9` (Apache-2.0). The acquired snapshot
hash is
`18309e334c0231266dcaba3f9b70f47e919b787190a3e5d22744b240048c0a7c`.
The CPU runtime used `sentence-transformers` 5.6.0, PyTorch 2.13.0+cpu,
`transformers` 5.13.1, `huggingface-hub` 1.23.0, `tokenizers` 0.22.2, and
`safetensors` 0.8.0. Ordinary search never downloads model weights; acquisition
is an explicit operator step, and a missing optional dense provider is reported
rather than silently relabelled as semantic search.

The executed dense build took 166.44 seconds wall time on the documented
baseline machine, used 725,828 KiB maximum resident memory, and completed with
zero index omissions. This single run proves build feasibility and manifest
coverage; repeated cold/warm performance characterization is reported
separately in Phase 6.

## Reproduction and verification

```bash
PYTHONPATH=backend .venv/bin/python -m app.indexing.chunker \
  chunk --overwrite --out-dir data/chunks
python data/evaluation/validate_section_quality_silver_v1.py \
  --database data/papers.db --evaluate-current
PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder \
  index --provider feature_hashing
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder \
  acquire-dense-model --device cpu
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder \
  index --provider dense --device cpu
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder \
  validate --provider feature_hashing
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder \
  validate --provider dense
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
PYTHONPATH=backend .venv/bin/python scripts/capture_phase1_evidence.py
```

At capture time, SQLite `quick_check` returned `ok`, foreign-key checking found
zero violations, both vector manifests validated, keyword coverage was 719/719,
and the smoke check reported all 17 checks passing. Restricted local corpus and
index bytes are prerequisites for the full snapshot and are not redistributed.
