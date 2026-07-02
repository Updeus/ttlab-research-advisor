# Feature Matrix

| Feature | Status | Evidence | Demo route | Limitation |
| --- | --- | --- | --- | --- |
| TTLAB discovery | Implemented | `app.ingestion.ttlab_page discover` writes seed JSON | Dashboard, Papers | TTLAB markup can change; re-run before demos |
| Seed import | Implemented | `app.ingestion.manual_import` upserts papers/authors | Dashboard, Papers | Imported metadata stays `needs_review` |
| PDF download | Implemented | Direct-PDF downloader with dry-run default | Paper detail | Does not follow publisher pages |
| PDF extraction | Implemented | PyMuPDF extraction diagnostics and status fields | Paper detail | Scanned PDFs are flagged, not OCR'd |
| Chunking | Implemented | Page-aware chunks in SQLite and local JSON | Paper detail, Search | Deterministic heading detection is simple |
| Keyword search | Implemented | SQLite FTS5/fallback keyword index | Search | Depends on extracted text quality |
| Semantic search | Implemented | Local hashing embeddings | Search | Offline hashing is lightweight, not a model embedding |
| Hybrid retrieval | Implemented | Combined keyword and semantic retriever | Search, Ask TTLAB | Ranking is simple and explainable |
| Ask TTLAB | Implemented | Stored RAG answers with citations and grounding | Ask TTLAB | Offline extractive provider, not a full LLM answerer |
| Thesis Extension Finder | Implemented | Ranked cited recommendations stored in SQLite | Thesis Extension Finder | Suggestions require supervisor review |
| Paper Intelligence | Implemented | PaperArtifact records and local generated JSON | Paper detail | AI-assisted drafts; review required |
| Podcast script | Implemented | Text-only two-speaker script artifact | Paper detail | No audio/TTS |
| Admin Review | Implemented | Review status updates and ReviewEvent audit trail | Admin Review | Local/demo no-auth workflow |
| Evaluation Dashboard | Implemented | Reads evaluation result JSON and templates | Evaluation | Missing files show `not_run`; metrics need reviewed cases |
| Topic/Author Explorer | Implemented | Topic, PaperTopic, AuthorTopic links and explorer APIs | Topic/Author Explorer | Deterministic/inferred unless reviewed; no graph library |
| Related papers | Implemented | Shared author/topic/venue/year/keyword/semantic scoring | Paper detail | Navigation aid, not novelty evidence |
| Demo prep helper | Implemented | Bounded `app.demo.prepare_demo --limit 25` command | CLI | Processes only limited local data by default |
