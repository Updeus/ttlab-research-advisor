# TTLAB Research Intelligence Platform

**From a publication archive to a source-traceable research-intelligence
platform.**

Developed as an MSc Data Science project, this platform ingests and inspects
TTLAB publications, searches full-paper content, answers questions with paper/
chunk/page evidence, discovers publication-derived topics and authors, and
generates explicitly labeled thesis-extension suggestions and paper-
intelligence drafts. It extends *Automating the
Collection, Display, Summarization and Podcasting of Academic Research* beyond
metadata and abstracts into full-text retrieval, source-traceable RAG,
administrative review, and controlled offline evaluation.

The platform is a research artefact, not a validated human advisor. Source-
traceable means that an output retains paper, chunk, page/section, snippet,
provider, timestamp, and review-state provenance. It does not mean that every
claim is correct, complete, novel, feasible, or supervisor-approved.

## Implemented system

- TTLAB archive discovery and deterministic operator-run seed import. Automated
  synchronization/promotion is fail-closed until an atomic active-generation
  switch exists; network/PDF work is not permitted in the production API.
- Allowlisted direct-PDF acquisition with file/size/page/redirect controls.
- PyMuPDF page extraction, PDF/title identity checks, scanned-page diagnostics,
  optional Tesseract OCR, and page-aware deterministic chunking.
- Author normalization/alias state, metadata provenance, explicit technical
  corpus eligibility, independent publication/rights/access state, and
  conservative section detection.
- Four user-facing retrieval modes:
  - keyword/FTS;
  - 256-dimensional deterministic feature hashing;
  - 384-dimensional learned dense retrieval using a pinned local
    `sentence-transformers/all-MiniLM-L6-v2` snapshot; and
  - hybrid retrieval with explicit heuristic configuration.
- Ask TTLAB with a pre-generation answerability gate, claim-level structural
  source links, citation pruning, requested/configured/effective provider
  provenance, and transient public requests by default. Automated source checks
  are capped at `support_unverified`; they do not assert entailment.
- Thesis Extension Finder with an evidence-only alternative and separate paper
  facts, paper-stated future work, inferred gaps, and system suggestions.
- Public/technical summaries, contributions, methods, limitations, future work,
  skills/evaluation plans, and text-only podcast scripts.
- Publication-derived Topic/Author Explorer and explainable related-paper links.
- Authenticated reviewer/admin mutations, actor-advertised capabilities,
  separate correction and review actions, human-admin-only publication/rights
  decisions, distinct `ai_reviewed` state, attributed append-only review events
  with a hash chain, and a visibly insecure loopback-only demo bypass.
- Route-based React interface with direct links, responsible-AI/freshness states,
  accessibility regression checks, and 360/768/1024/1440 px overflow tests.
- Executed retrieval, QA faithfulness/citation, recommendation-proxy,
  topic/author, section-quality, and generated-output evaluations.
- Reproducibility, performance, release-sanitization, security, privacy, threat-
  model, and deployment tooling.

The ambiguous legacy retrieval value `semantic` is rejected. Feature hashing is
available only as `feature_hashing` and is never presented as a learned semantic
encoder.

## Evidence snapshot

The counts below describe the frozen **technical evaluation corpus**, not an
approved public collection. Technical eligibility answers whether a source can
enter controlled experiments. Public metadata and source-text delivery require
separate `published`, `rights=cleared`, and `metadata_only|searchable` decisions.
Legacy rows migrate to `pending_review` / `unknown` / `hidden`, so the public
projection is empty until an authorized human administrator supplies per-paper
decisions. The protected Admin Publication Preview is labeled `NOT PUBLIC` and
is never used as a fallback for public routes.

The immutable historical-v1 experimental corpus is
`corpus-04a010207327069a`. It is retained for comparison and is not described as
the current remediation snapshot; the latter is bound only by the completed v2
freeze receipt and manifest:

| Inventory | Count |
|---|---:|
| Catalogue records | 134 |
| Records with available local PDF content | 98 |
| Eligible experimental papers | 96 |
| No-text records retained as `needs_review` | 36 |
| Metadata/PDF mismatches excluded | 2 |
| Raw chunks | 735 |
| Eligible chunks | 719 |
| Feature-hashing index coverage | 719/719 |
| Learned-dense index coverage | 719/719 |

The following measurements are retained **historical v1 AI-assisted evidence**;
they describe the pre-remediation snapshot above and are not current-runtime or
prospective-v2 results. The Phase 2 held-out retrieval set has 20 cases (19 answerable, one
unanswerable). Keyword retrieval led MRR at 0.9474; dense MRR was 0.9386;
tuned-hybrid MRR was 0.8596. No tuned-vs-baseline comparison survived the
Holm-Bonferroni experiment-family correction. The result is a negative finding
for hybrid superiority, not a reason to hide the baseline.

The 50-case AI-assisted QA review found strict supported-claim rate 0.995, but
citation correctness 0.625, strict answer-point coverage 0.1358, and zero
abstentions on four unanswerable cases. The 28-profile recommendation proxy
study found a full-minus-evidence-only relevance difference of 0.0238 (95% CI
-0.0238 to 0.0714), which does not demonstrate improvement. These are AI-
reviewed formative/proxy results, not human ratings.

The validated full performance profile completed all 17 required stages with
102 timed samples, 102 maximum-RSS records, and zero failures. It ran on WSL2
Linux using an AMD Ryzen 7 5800X, 16 logical CPUs, 4,012,360 KiB visible RAM,
CPU execution, Python 3.12.3, Node 24.14.1, and npm 11.11.0. This is a bounded,
single-process, concurrency-one local baseline; three repetitions give only
descriptive medians/p95 values and do not establish capacity, saturation,
multi-user behaviour, or production service levels.

The external sanity check mapped three pinned CC BY JATS XML documents into the
production chunker contract and obtained 3/3 fixed lexical top-one matches. It
did not exercise the main PDF acquisition/extraction path and is neither a
cross-domain retrieval-quality result nor broad external validation.

The current local manuscript build contains a 6-Letter-page IEEEtran paper
with 21 cited references at `build/ieee-paper.pdf` and an 86-A4-page thesis at
`build/thesis.pdf`. The exact final-candidate counts belong in the peer-review
readiness report and must be remeasured after the clean reproduction. An
editable Word derivative is available at
`build/thesis-editable.docx`; it preserves native Word text, tables, equations,
styles, contents/list fields, and IEEE references while embedding the
code-rendered diagrams as images. LaTeX remains the canonical source. These
standalone document builds do not replace the
clean source-candidate reproduction, PDF preflight, and clean-release acceptance
gates described below.

See [Methodology](docs/METHODOLOGY.md), [Evaluation
Protocol](docs/EVALUATION_PROTOCOL.md), and
`docs/peer_review_readiness/FINAL_READINESS_REPORT.md` for methods, intervals,
raw evidence paths, final candidate identities, and limitations. The latter is
the current closure record once the final isolated run is accepted;
`docs/FINAL_STATUS.md` is a superseded historical-v1 checkpoint.

## Repository layout

```text
backend/       FastAPI, SQLModel, ingestion, retrieval, intelligence, evaluation
frontend/      React, Vite, TypeScript, Vitest/axe, Playwright
data/seed/     redistributable seed metadata
data/evaluation/ schemas, silver labels, review passes, validators
artifacts/     versioned baseline and Phase 1–6 sanitized evidence
docs/          methodology, design, governance, evaluation, reproduction
paper/         editable IEEEtran manuscript sources
thesis/        modular thesis sources, figures, evidence generation
scripts/       demo, reproduction, and support commands
build/         compiled documents and local sanitized releases
```

Runtime databases, PDFs, extracted/chunk text, indexes, model caches, private
prompts, and histories are local/ignored. They are not distributed by the
sanitized release.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

Optional learned-dense and OCR dependencies:

```bash
python -m pip install -r backend/requirements-dense.txt
python -m pip install -r backend/requirements-ocr.txt
```

Dense model acquisition is an explicit operator action. Normal search never
downloads model weights:

```bash
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder acquire-dense-model
```

The pinned model revision is
`826711e54e001c83835913827a843d8dd0a1def9`. The core keyword and feature-
hashing paths remain available when the dense extra/model is absent, with an
explicit provider warning rather than silent relabeling.

## Local demo

The one-command loopback demo is:

```bash
./scripts/run_everything.sh
```

Useful variants:

```bash
./scripts/run_everything.sh --skip-downloads
./scripts/run_everything.sh --serve-only
./scripts/run_everything.sh --serve-only --no-ollama
./scripts/run_everything.sh --verify-only
```

The launcher binds locally and opts into a clearly labeled insecure demo admin
bypass. Responses carry `X-TTLAB-Insecure-Demo: true`. Never enable this bypass
in production. Direct backend startup is fail-closed for protected routes unless
environment-configured reviewer/admin actors are supplied.

Prepare a bounded UI dataset separately:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

The bounded feature-hashing output is isolated under `data/indexes/demo/` and
does not update authoritative index status. It is for interface demonstration,
not research metrics or full-corpus coverage claims.

Manual servers:

```bash
uvicorn app.main:app --reload --app-dir backend
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`; API documentation is at
`http://127.0.0.1:8000/docs`.

## Corpus preparation

Discover/import permitted publication metadata. Discovery writes to runtime
state, not the tracked reviewed seed:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.ttlab_page discover \
  --url https://lab.tt/index.php/category/pub/ \
  --max-pages 2 \
  --out data/runtime/ttlab_publications_discovered.json
PYTHONPATH=backend .venv/bin/python -m app.ingestion.manual_import \
  --seed data/runtime/ttlab_publications_discovered.json
```

Process authorized local inputs and rebuild complete representations:

```bash
env TTLAB_SERVICE_ROLE=offline_worker \
  TTLAB_SYNC_EXECUTION_MODE=offline_single_writer \
  PYTHONPATH=backend \
  .venv/bin/python -m app.ingestion.pdf_downloader --from-db --download
env TTLAB_SERVICE_ROLE=offline_worker \
  TTLAB_SYNC_EXECUTION_MODE=offline_single_writer \
  PYTHONPATH=backend \
  .venv/bin/python -m app.ingestion.pdf_parser extract --overwrite
PYTHONPATH=backend .venv/bin/python -m app.indexing.chunker chunk --overwrite
PYTHONPATH=backend .venv/bin/python -m app.ingestion.generation_reconciler reconcile
PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider feature_hashing
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider dense --device cpu
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
```

The two explicit worker variables are a safety boundary, not a production
server setting. PDF network and parser operations fail in the default API role;
run them only in an isolated staging copy without serving, reviewer, or model
credentials. Re-extraction and re-chunking use overwrite deliberately so every
generation link and manifest is rebuilt from the authorized source bytes.

The vector builders write immutable payload/manifest generations and atomically
replace a checksum-bound `current` pointer only after authoritative database
status is committed. Readers hold a shared lock, resolve only that pointer, and
recompute corpus/payload identities; a partial, stale, corrupt, differently
configured, unpointed, or mismatched generation fails instead of falling back
to an older compatibility file. A failed build restores the previous pointer
and database status. Bounded/demo builds must use `data/indexes/demo/`, cannot
update authoritative status, and cannot support published results.

### Automated synchronization boundary

Automated corpus synchronization is intentionally unavailable. The worker and
Admin trigger fail before discovery or mutation with
`atomic_generation_promotion_not_implemented`; configuration cannot enable a
partially committed promotion. This preserves the last active corpus when any
future scheduled run would otherwise fail between metadata, extraction, chunk,
index, topic, and file phases.

Corpus changes therefore use the explicit commands above in an isolated copy.
An operator must validate the complete staged database/files/indexes, stop API
writes, take a recoverable backup, and deliberately replace the active snapshot.
The repository does not automate that final switch and does not claim online or
multi-process atomic promotion. The protected Admin overview reports the reason
the trigger is unavailable. See [Deployment](docs/DEPLOYMENT.md) for the
remaining operator controls.

## Use the intelligence features

Ask a question:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.rag_answerer ask \
  "Which TTLAB papers discuss RAG?" \
  --mode keyword --top-k 5 --scope public
```

Generate structured extension suggestions:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.extension_recommender recommend \
  --interests "RAG, web apps, education" \
  --skills Python React FastAPI \
  --available-time semester \
  --project-type "software prototype" \
  --data-constraints "prefer public or synthetic data" \
  --preferred-difficulty medium \
  --top-k 5 --mode keyword --scope public
```

Both commands default to `--scope public` and do not persist the submitted
question/profile or generated output. In the checked-in data state that public
projection is intentionally empty: technical eligibility does not substitute
for editorial, rights, extraction, and searchable-access approval. An
authorized offline evaluator may add `--scope technical` to inspect the frozen
research corpus. Persistence is a separate explicit `--persist` option and
should be used only in an access-controlled local workflow.

Inspect publication-derived topic evidence:

```bash
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic "RAG"
```

Optional Ollama composition requires an operator allowlist mapping the requested
model name to the exact digest reported by the local service. Mutable or
unapproved tags fail closed, and the configured digest is checked before and
after generation. Ollama's standard generation response normally identifies a
model tag but not an immutable digest. In that case the output is honestly
attributed to the tag with `generation_time_digest_verified=false`; the
pre/post checks narrow tag-swap risk but are not a generation-time digest
attestation. If the service or configured digest is unavailable, the
application records the requested/configured/effective provider and explicit
offline fallback reason. The historical QA study contains no Ollama quality or
latency comparison because the service was unavailable.

## Evaluation and reproduction

Validate the committed evidence:

```bash
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_retrieval_silver_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_qa_faithfulness_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_recommendation_proxy_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_topic_author_silver_v1.py
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_section_quality_silver_v1.py --evaluate-current
PYTHONPATH=backend .venv/bin/python -m app.evaluation.generated_output_review
PYTHONPATH=backend .venv/bin/python data/evaluation/validate_peer_review_remediation_v2.py --static-only
```

The prospective remediation-v2 runner, validator, evaluation dashboard, and
sanitized release use one versionable package location:
`artifacts/peer_review_remediation/v2/`. Rights-sensitive full-text raw outputs
remain outside the repository and release tree. The full reproduction command
regenerates this canonical package in its detached source snapshot; it does not
create a second committed artifact hierarchy.

Within each fresh frozen workspace, the fixed order is `prepare` (validate the
locked environment and freeze code, datasets, technical-corpus generations,
splits, OCR configuration, and source locators), one `evaluate` invocation,
then independent package validation. The first accepted source candidate is the
confirmatory run. A later full run is a deterministic replication against an
unchanged protocol/case set—not another opportunity to tune, relabel, or select
results. It
uses technical scope only and does not exercise or validate the public
projection. Its two shuffled passes are repeated applications of one AI review
procedure: they provide AI-silver repeatability evidence, not human validation,
inter-rater reliability, semantic entailment, novelty, or student/supervisor
usefulness. Do not invoke `evaluate` merely to obtain a manuscript layout; the
full reproduction owns the prospective run.

Re-run the retrieval experiment or external sanity acquisition:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_experiment
PYTHONPATH=backend .venv/bin/python -m app.evaluation.external_sanity
```

One-command paths:

```bash
make reproduce-quick
make reproduce
make release
```

The full path requires a separately authorized database/PDF set and the pinned
dense model. The quick path cannot recreate restricted corpus-dependent
experiments and deliberately uses `paper-layout`/`thesis-layout`, whose visible
`not run` v2 macros cannot pass final readiness validation. A completed v2
package must pass `make peer-review-v2-validate` before `make paper` or the
frozen thesis asset/build path will consume it. The full performance artifact is
committed and independently validated; it is not a scalability claim. Candidate
delivery runs `make reproduce` and `make release` before tag/push. The
reproduction manifest binds the clean source-candidate commit/tree that was
actually executed. A later evidence commit may add only validated generated
artifacts, retained attestations, PDFs, and closure documentation; it is not
described as the reproduced commit. Any source, protocol, case, application, or
manuscript change requires a new source-candidate run. Those commands are
fail-loud gates rather than evidence inferred from an earlier run. See
[Reproducibility](docs/REPRODUCIBILITY.md), [Data and Artifact
Availability](docs/DATA_AND_ARTIFACT_AVAILABILITY.md), and
`docs/peer_review_readiness/FINAL_READINESS_REPORT.md` for the final recorded
outcomes.

## Verification

Always-runnable engineering checks are:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend audit --audit-level=high
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
```

Before the first accepted v2 confirmatory execution, layout-only manuscript
checks are explicitly:

```bash
make paper-layout
make thesis-layout
.venv/bin/python scripts/validate_manuscripts.py --allow-v2-not-run
```

Those commands are presentation probes, not final evidence. Final manuscript
generation requires the completed, validated v2 package and uses:

```bash
make peer-review-v2-validate
make paper
make thesis-assets-frozen
make thesis-compile
make thesis-word
make thesis-word-validate
```

Engineering verification is separate from quality evaluation. Exact final test
counts and acceptance-gate PDF preflight results are recorded in
`docs/peer_review_readiness/FINAL_READINESS_REPORT.md`. That report identifies
both the reproduced source-candidate commit/tree and the later evidence commit;
the latter is not relabeled as the exact reproduced source.
The current 6-Letter-page paper and 86-A4-page thesis satisfy the local page
gates but remain subject to clean source-candidate reproduction and external
venue/institution checks.

See [`thesis/word/README.md`](thesis/word/README.md) for Word editing,
field-update, figure-source, and rebuild guidance.

## API highlights

Public/read surfaces fail closed to the independently approved public
projection and include:

- `GET /health`, `GET /ready`, `GET /api/stats`
- `GET /api/papers`, `GET /api/papers/{paper_id}`
- `GET /api/search?q=RAG&mode=dense`
- `POST /api/ask`
- `POST /api/recommendations/extensions`
- `GET /api/topics`, `GET /api/authors`, `GET /api/explorer/overview`
- `GET /api/evaluation/dashboard`

Protected reviewer/admin operations include history/item routes, a labeled
publication preview (including full extracted chunks), persisted artifact
generation, separate correction/review actions, capability discovery, paginated
review events, and admin diagnostics. Public Ask/Finder requests are transient
and do not store question/profile content by default. Technical evaluation scope
is available only to named offline/evaluation call sites, never through an
anonymous request parameter.

## Security, privacy, accessibility, and release

- [Frontend requirements](docs/FRONTEND_REQUIREMENTS.md)
- [Security](docs/SECURITY.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Privacy](docs/PRIVACY.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Ethics and governance](docs/ETHICS_AND_GOVERNANCE.md)
- [External submission checks](docs/EXTERNAL_SUBMISSION_CHECKS.md)

Production mode requires explicit trusted hosts/CORS origins, HTTPS public base
URL, and at least one environment-configured active admin actor. Bearer tokens
are represented in configuration only by SHA-256 digests and are never
committed. Token mode does not use cookies; reverse proxy, TLS, monitoring,
retention, incident response, and institutional identity remain deployment
responsibilities.

Automated axe, keyboard, route, responsive-overflow, and Chromium checks provide
regression evidence only. They do not establish WCAG conformance or conformance
with screen readers, magnification, voice control, or other assistive
technologies.

## Limitations

- One laboratory and small held-out cohorts limit external validity.
- Silver labels and usefulness judgments come from one AI-assisted procedure,
  not recruited humans or independent assessors.
- The offline extractive answerer is well sourced at claim level but often
  incomplete/off-topic and failed all recorded unanswerable abstentions.
- Hybrid retrieval did not outperform keyword or dense baselines in the held-
  out study after family correction.
- Recommendation feasibility, novelty, data access, and supervisor fit require
  external human/institutional confirmation.
- Topic/author evidence is publication-bounded; 13 possible identity merges
  remain unresolved.
- Current corpus evidence reports no OCR-processed pages and no OCR accuracy.
- The full performance result is a single-host, concurrency-one baseline;
  capacity, scaling, multi-browser/manual assistive-technology conformance,
  public deployment, and human advisory validation are not established.
- No audio/TTS pipeline is implemented; podcast output is a cited text draft.

Unknown information is omitted or retained as uncertainty. It is never filled
with invented metadata, approvals, metrics, or results.
