# System Design

## Design intent

The TTLAB Research Intelligence Platform is a bounded local-first system that
turns a laboratory publication catalogue into page-aware discovery, source-
traceable question answering, publication-derived exploration, and explicitly
labeled extension suggestions. The design prioritizes inspectability and
degraded offline operation over distributed scale.

Source-traceable means that an output can retain a paper ID, chunk ID,
page/section, snippet or source hash, provider/model, timestamp, and review
state. It is not a synonym for factual correctness or complete entailment.

## Logical architecture

```text
permitted catalogue/PDF sources
  -> acquisition and identity audit
  -> page extraction / optional OCR
  -> deterministic section-aware chunks
  -> authoritative corpus snapshot
       |-> SQLite keyword/FTS index
       |-> 256-d feature-hashing index + manifest
       |-> 384-d learned-dense index + manifest
  -> retrieval and explicit reranking configuration
       |-> Search
       |-> Ask TTLAB -> answer/citation verifier
       |-> evidence-only or full Extension Finder
       |-> paper intelligence / podcast text
       |-> controlled topics / author evidence / related papers
  -> SQLModel/SQLite + generated artifacts + append-only review events
  -> FastAPI public/read and protected mutation routes
  -> React route-based evidence and review interface
  -> evaluation artifacts, reproducibility manifest, sanitized release
```

## Backend modules

The FastAPI application is rooted at `backend/app/main.py`. Startup validates
security configuration, creates/migrates tables, and rejects any present
authoritative vector index whose manifest does not match the eligible corpus.
`/ready` requires a complete keyword index and complete feature-hashing index;
a dense index is optional only when absent. A present partial, stale, or corrupt
dense index is not an acceptable degraded state.

### Acquisition and corpus processing

- `ingestion/ttlab_page.py` discovers and normalizes catalogue records without
  treating scraped fields as verified facts.
- `ingestion/manual_import.py` idempotently imports seeds and author aliases.
- `ingestion/pdf_downloader.py` limits permitted hosts, redirects, file size,
  URL schemes, and PDF validation; it does not bypass authentication or
  paywalls.
- `ingestion/metadata_cleaner.py` repairs known parser artifacts, audits
  paper/PDF title identity, and preserves unresolved author state.
- `ingestion/pdf_parser.py` performs page extraction, records per-page method
  and diagnostics, and can invoke optional OCR from `ingestion/ocr.py`.
- `indexing/chunker.py` deterministically emits page-aware chunks with stable
  source hashes and conservative section labels.

Every catalogue record keeps an eligibility/review state. The current frozen
corpus has 134 records, 96 eligible papers, 719 eligible chunks, 36 no-text
`needs_review` records, and two metadata/PDF mismatches excluded with their 16
chunks. Catalogue visibility is distinct from experimental eligibility.

### Retrieval and index integrity

- `indexing/keyword_search.py` builds and validates the SQLite FTS/fallback
  lexical representation over all eligible chunks.
- `indexing/embedder.py` supplies provider-modular feature-hashing and learned-
  dense encoders, atomic index writes, explicit bounded-demo role, and complete
  manifests.
- `indexing/vector_store.py` loads only a valid provider/index pair and performs
  cosine search.
- `indexing/retriever.py` combines candidate pools under a serializable
  `RetrieverConfig`, with separately switchable query-expansion, metadata,
  section, evidence, topic, and diversity terms.

An authoritative vector manifest contains the corpus snapshot ID/hash, ordered
chunk IDs/source hashes, eligible paper/chunk counts, provider/model/revision,
model artifact hash, dimension, normalization, configuration hash, build time,
code commit, index checksum, index role, and completeness state. SQLite status
is a diagnostic, not the source of truth. A bounded demo writes only to
`data/indexes/demo/` and cannot set authoritative completeness.

Supported request modes are:

- `keyword` — lexical FTS/fallback;
- `feature_hashing` — deterministic 256-dimensional signed token hashing;
- `dense` — learned 384-dimensional `all-MiniLM-L6-v2` at pinned revision
  `826711e54e001c83835913827a843d8dd0a1def9`; and
- `hybrid` — explicit keyword/vector/heuristic combination.

`semantic` is accepted only as a legacy alias for feature hashing. When the
dense dependency/model/index is absent, the response exposes provider state and
warning instead of presenting hashing as learned dense retrieval.

### Intelligence services

- `intelligence/rag_answerer.py` retrieves evidence, calls an allowed answer
  provider, preserves retrieved chunks/citations/provider metadata, verifies
  structural grounding, and defaults public calls to `persist=False`.
- `intelligence/citation_verifier.py` checks citation mapping and lexical
  support. Runtime `grounded` is a structural/lexical status, not a truth label.
- `intelligence/extension_recommender.py` provides an evidence-only mode and a
  full structured Finder. The full path separates paper-supported facts,
  explicit/inferred/not-found gaps, and newly generated suggestions.
- `intelligence/recommendation_verifier.py` checks citations, gap labels, data
  warnings, skills gaps, and timeline risk.
- `intelligence/paper_artifact_generator.py` produces cited public/technical
  summaries, contributions, methods, limitations, future work, extensions,
  skills, and evaluation-plan bundles.
- `intelligence/podcast_script_generator.py` produces cited text-only scripts;
  there is no audio/TTS pipeline.
- `intelligence/topic_explorer.py` applies the retained controlled lexical
  vocabulary, derives author-topic evidence only from eligible publication
  authorship, and explains related-paper scores.
- `intelligence/llm_provider.py` keeps deterministic offline extraction as a
  supported path and isolates optional local Ollama/external adapters.

The platform never treats a generated extension as paper-stated future work.
Potential researcher fit is a bibliographic discovery hint, not confirmation of
availability, endorsement, expertise beyond the corpus, or supervision.

### Persistence and review

SQLModel models cover papers, authors/aliases, chunks, topics/links, RAG
answers, thesis recommendations, paper artifacts, and `ReviewEvent`. Review
states distinguish `needs_review`, `ai_reviewed`, human review/approval states,
rejection, and `needs_reprocess` where applicable.

Review events record item/action, prior/new state, actor ID/name/type/role,
request ID, notes/diff, timestamp, previous-event hash, and event hash. SQLite
triggers prevent application/database updates or deletes of event rows. The
hash chain and triggers increase auditability but do not make a database
tamper-proof against its filesystem owner.

The executed generated-output pass inspected 48 historical records. Fourteen
paper artifacts and seven recommendations are `ai_reviewed`; 27 unreproducible
historical answers are `needs_reprocess`. Re-running the same review version is
idempotent.

### Evaluation and reproducibility

`backend/app/evaluation/` implements correct retrieval metrics, frozen-candidate
experiments, bootstrap/paired statistics, claim-level QA review, recommendation
proxy review, topic/author comparison, generated-output review, external sanity,
and performance measurement. Aggregate results are accepted only with their raw
cases, input/config hashes, and validators.

The committed full performance artifact independently validates 17 required
stages, 102 timed samples, 102 RSS records, and zero failures on WSL2 Linux with
an AMD Ryzen 7 5800X, 16 logical CPUs, 4,012,360 KiB visible RAM, and CPU
execution. The harness dispatches one probe process at a time and uses only
three cold and three warm repetitions. It is a bounded local latency/resource
baseline, not a capacity, saturation, concurrency, endurance, or production
service-level test.

The external sanity path maps three pinned CC BY JATS XML documents into the
production chunker contract and checks three fixed lexical top-one matches. It
does not exercise the main PDF acquisition/extraction pipeline and does not
support a cross-domain retrieval-quality or broad external-validity claim.

`backend/app/reproducibility/` constructs local run manifests and an allowlist-
based deterministic release. Restricted passages in otherwise permitted JSON
are replaced with hash/length records. PDFs, databases, indexes, private
prompts/histories, local paths, and secrets are excluded and scanned.
The final clean commit is accepted for delivery only after the fail-loud full
reproduction and sanitized-release commands complete; a prior benchmark or
candidate bundle is not substituted for that gate.

## Data contracts

### Paper and extraction

Paper records retain catalogue/source fields, local acquisition status,
eligibility and exclusion reason, PDF/title identity state, extraction/OCR
state, metadata provenance/review fields, and review timestamps. Unknown DOI,
abstract, keyword, date, venue, or identity fields remain empty/unresolved
rather than inferred.

Extraction JSON retains:

```text
paper_id, source/local PDF identity, page_count, pages[], text hashes,
per-page native/OCR method and status, diagnostics, warnings, extraction status
```

Chunk records retain:

```text
chunk_id, paper_id, ordinal, page_start/page_end, section, text,
character/word/token estimates, source_hash, eligibility/index status
```

### Retrieval response

```text
query, expanded_query, mode, vector_provider, retriever_config,
warnings, result_count, results[]

result:
  rank, paper_id/title/authors/year, chunk_id, page range, section,
  snippet, component/final scores, source and eligibility metadata
```

Public APIs redact server-local storage paths.

### Ask response

```text
question, answer, provider/model, retrieval mode/config,
citations[], retrieved_chunks[], grounding status, unsupported warnings,
generation timestamp, persistence/review state
```

Public `POST /api/ask` is transient. History and item retrieval require a
reviewer/admin actor. Provider selection must be in the deployment allowlist.

### Extension response

Each result includes ranked paper identity, fit rationale, source-supported
facts, explicit/inferred gap status, system suggestion, MVP, stretch goals,
skills/gaps, data needs/availability, evaluation plan, difficulty, risk,
implementation time, related papers, researcher-fit hint, citations, and
warnings. Public requests are transient. History/item routes are protected.

### Paper artifacts

Public reads are limited to eligible papers and public-safe artifact state.
Generating an artifact for one paper requires reviewer authorization; batch
generation requires admin. Payloads retain provider/model/time, support labels,
source chunk IDs/citations, grounding, warnings, and review state.

## API authorization boundary

Public/read routes include health/readiness, public paper metadata, search,
transient Ask/Finder, diagnostics with local paths redacted, explorer views, and
the read-only evaluation dashboard. Protected routes include:

- RAG/recommendation histories and individual persisted records;
- full extracted chunks and non-public review detail;
- paper artifact generation and batch generation;
- all admin review, correction, extraction decision, and review-event routes.

Bearer actors are configured through `TTLAB_AUTH_ACTORS_JSON` using only token
SHA-256 digests and stable actor metadata. Production requires at least one
active admin actor, HTTPS public base URL, exact HTTPS CORS origins, explicit
trusted hosts, and disabled demo bypass. No default secret is committed.

Public request bodies are limited and generation endpoints are rate-limited.
Downloader hosts and sizes are bounded. Security middleware supplies request
IDs, safe headers, path/body-minimized logs, and a visible security-mode header.
Token mode does not use cookies, so browser CSRF tokens are not the applicable
control; exact CORS, HTTPS, token secrecy, and authorization are.

## Frontend architecture

`frontend/src/App.tsx` defines BrowserRouter routes for:

```text
/
/papers
/papers/:paperId
/search
/ask
/ask/:paperId
/extensions
/explorer
/explorer/topics
/explorer/topics/:topicId
/explorer/authors
/explorer/authors/:authorId
/evaluation
/admin
```

The interface preserves browser history, reload/deep links, route titles,
focus restoration, current-link state, a skip link, a deterministic 404, and
responsive layouts. It displays index/evaluation freshness, evidence locators,
provider/model/timestamp, review type/status, generated-content notices, and
unsupported/partial warnings. Student profile and question content remains in
component/request memory and is not written to browser storage or URLs. Admin
bearer tokens remain in page/module memory and disappear on reload.

The automated frontend checks cover route loading/history, responsible-AI
labels, source citations, error/no-evaluation states, keyboard skip navigation,
anonymous admin protection, axe regressions on representative routes, and
horizontal overflow at 360/768/1024/1440 px. They do not establish full WCAG
conformance across assistive technologies or browsers.

## Deployment and operational boundaries

The repository supplies configuration and documentation, not a deployed
production service. An operator must provide TLS/reverse proxy, process/service
management, secrets, backups/restore tests, retention, monitoring/alerting,
institutional identity or token provisioning, incident handling, correction/
appeal contacts, and SPA fallback routing. Production must not expose local
API docs or the insecure demo bypass.

## Current empirical design consequences

- Complete index coverage is an integrity result, not a relevance score.
- Keyword and dense retrieval both outperformed the tuned hybrid on held-out
  MRR; hybrid superiority is not claimed.
- QA claims were usually source-supported, but citations were often only
  partial and answer-point coverage/abstention were poor.
- Recommendation and topic results are AI-assisted proxy/silver evidence, not
  human validation.
- The full benchmark completed without sample failures, but its single-host,
  concurrency-one design does not establish scalability or production capacity.

See `docs/METHODOLOGY.md`, `docs/EVALUATION_PROTOCOL.md`, and
`docs/FRONTEND_REQUIREMENTS.md` for the executed research design and detailed
verification boundary.
