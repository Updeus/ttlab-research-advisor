# Feature Matrix

| Feature | Implemented evidence | Public surface | Verification | Residual limitation |
|---|---|---|---|---|
| Catalogue discovery/import | `app.ingestion.ttlab_page`, `manual_import`, seeds | Papers/Dashboard | parser/import tests | Source markup and metadata can change; unknown fields remain unverified |
| PDF acquisition | allowlisted/size/redirect/signature/path controls | Paper status | downloader/security tests | Permitted direct sources only; no paywall bypass |
| Extraction and optional OCR | page provenance, scan diagnostics, PyMuPDF, optional Tesseract | Paper Detail | parser/OCR tests; Phase 1 evidence | Frozen corpus used no OCR; no OCR accuracy claim |
| Corpus/PDF identity | eligibility/exclusion fields and title audit | Paper/Evaluation/Admin state | Phase 1 manifest/tests | 36 no-text records and two mismatches excluded |
| Page-aware chunking/sections | deterministic chunk IDs/hashes/pages; conservative headings | Paper Detail/evidence cards | chunk/section tests; 40-case silver set | 199 eligible chunks remain `Unknown` |
| Keyword retrieval | complete eligible FTS/fallback representation | Search/Ask/Finder | retrieval tests/Phase 2 | Sensitive to vocabulary/extraction quality |
| Feature hashing | complete 256-d signed-token index/manifest | Search | integrity/retrieval tests/Phase 2 | Lexical-feature baseline, not learned semantic search |
| Learned dense retrieval | complete pinned 384-d MiniLM index/manifest | Search | integrity/retrieval tests/Phase 2 | Optional local model; dense MRR not significantly above keyword |
| Hybrid retrieval | explicit configurable combination and heuristics | Search/Ask/Finder | ablation/sensitivity/Phase 2 | Tuned hybrid did not demonstrate held-out superiority |
| Ask TTLAB | transient answer, citations, chunks, provider/time/warnings | `/ask`, `/ask/:paperId` | Ask tests/50-case QA review | Low answer-point coverage; failed recorded unanswerable abstentions |
| Local Ollama boundary | model listing/selection/fallback | Ask | provider tests | Recorded service unavailable; no benchmark result claimed |
| Thesis Extension Finder | evidence-only/full structured modes | `/extensions` | recommendation tests/28-profile proxy review | AI proxy only; feasibility/novelty/supervisor fit external |
| Paper intelligence | cited summary/contribution/method/limitation/future-work bundles | Paper Detail | artifact tests/generated-output review | `ai_reviewed` is not human approval |
| Podcast scripts | cited text dialogue | Paper Detail | artifact tests/review | No audio/TTS; clarity not user-validated |
| Topic Explorer | controlled lexical labels and evidence | `/explorer/topics*` | 60-case lexical-vs-dense evaluation | Recall limited; vocabulary bounded |
| Author Explorer | canonical routing, aliases, eligible-publication topic evidence | `/explorer/authors*` | author audit/tests | 13 possible identity merges unresolved; no availability/endorsement claim |
| Related papers | explainable shared evidence/similarity reasons | Paper Detail | explorer tests | Navigation aid, not novelty evidence |
| Admin review | role-protected corrections/state transitions | `/admin` | auth/admin/security tests | Institutional identity/lifecycle remains deployment-specific |
| Review audit trail | attributed, hash-chained, append-only event rows | Admin | trigger/hash/idempotence tests | DB owner can still rewrite the file; not WORM storage |
| Evaluation dashboard | result availability, schema state, metrics/freshness | `/evaluation` | dashboard/frontend tests | AI silver/proxy results; missing files remain `not_run` |
| Route/accessibility states | BrowserRouter, focus/skip/404, responsive/error states | all primary routes | Vitest/axe/Playwright/overflow | Automated single-browser checks are neither WCAG nor assistive-technology conformance |
| Security/privacy | bearer roles, fail-closed production, limits, CORS/hosts, transient public inputs | API/Admin notices | targeted backend/frontend tests | TLS, proxy, monitoring, retention, incident process external |
| Reproducibility/release | isolated one-command runner and deterministic sanitized bundle | documentation/build outputs | release/reproduction tests | Full run needs authorized PDFs/model; exact-commit fail-loud acceptance is required before tag/push |
| Performance harness | required pipeline/API/frontend stages, cold/warm/RSS | evidence only | full artifact + independent validator: 17 stages/102 samples/0 failures | Single WSL2 host, concurrency one, three repeats; no capacity/scaling/SLO claim |
| Editable manuscripts | modular LaTeX/BibTeX and reproducible figure/table generators | `build/ieee-paper.pdf`, `build/thesis.pdf` | current builds: 8 Letter pages and 74 A4 pages, respectively | Exact-final-commit acceptance rebuilds/preflights both; venue acceptance/PDF eXpress is external |
| External JATS sanity | pinned CC BY JATS XML mapped into production chunker contract | evidence only | 3/3 fixed lexical top-one matches | Does not exercise main PDF ingestion or establish cross-domain retrieval quality |
