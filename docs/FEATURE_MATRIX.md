# Feature Matrix

| Feature | Implemented? | Evidence in app | Backend/API | Frontend route | Test coverage | Limitation |
| --- | --- | --- | --- | --- | --- | --- |
| TTLAB publication discovery | Yes | Seed records and Papers page | `app.ingestion.ttlab_page`, `data/seed/*.json` | Papers | Parser fixture tests | Live TTLAB markup can change |
| PDF download | Yes | PDF/local path status | `app.ingestion.pdf_downloader` | Paper Detail | Downloader tests | Direct PDF URLs only |
| Full-paper extraction | Yes | Extraction diagnostics, page/word counts | `app.ingestion.pdf_parser`, `/api/papers/{id}/extraction` | Paper Detail | Parser tests | No OCR for scanned PDFs |
| Chunking | Yes | Page-aware chunk previews | `app.indexing.chunker`, `/api/papers/{id}/chunks` | Paper Detail | Chunker tests | Deterministic section detection is simple |
| Keyword search | Yes | Keyword results and snippets | `/api/search`, `app.indexing.keyword_search` | Search | Retrieval tests | Depends on extracted text quality |
| Semantic search | Yes | Semantic mode and diagnostics | `/api/search`, `app.indexing.embedder` | Search | Retrieval tests | Uses local hashing embeddings |
| Hybrid retrieval | Yes | Hybrid search results with smarter ranking | `/api/search?mode=hybrid`, `app.indexing.retriever` | Search, Ask TTLAB, Thesis Extension Finder | Retrieval tests | Deterministic scoring, not a learned reranker |
| Ask TTLAB | Yes | Answer, citations, grounding status, model selector | `/api/ask`, `/api/ask/diagnostics` | Ask TTLAB | Ask tests | Local model answers still need citation review |
| Local Ollama models | Yes | Red/yellow/green model selector and fallback warnings | `/api/llms/local`, `app.intelligence.llm_provider` | Ask TTLAB | Ask/provider tests | Requires local Ollama for model answers |
| Ollama benchmark baseline | Yes | Generated local benchmark JSON/CSV | `app.evaluation.ollama_benchmark` | Ask TTLAB model strip after results | Benchmark tests | Machine-specific, not thesis quality evidence alone |
| Thesis Extension Finder | Yes | Ranked recommendations with citations | `/api/recommendations/extensions` | Thesis Extension Finder | Recommendation tests | Suggestions need supervisor review |
| Paper Intelligence | Yes | Summary/limitations/future work/skills/evaluation tabs | `/api/papers/{id}/artifacts/*` | Paper Detail | Artifact tests | AI-assisted, unreviewed by default |
| Podcast script generation | Yes | Text-only dialogue script with citations | `app.intelligence.podcast_script_generator` | Paper Detail | Artifact/podcast tests | No audio/TTS |
| Topic Explorer | Yes | Topic cards, topic detail, evidence snippets | `/api/topics`, `/api/topics/{id}` | Topic/Author Explorer | Topic explorer tests | Deterministic/inferred unless reviewed |
| Author Explorer | Yes | Author profiles, topics, papers, coauthors | `/api/authors`, `/api/authors/{id}` | Topic/Author Explorer | Topic explorer tests | Author identity normalization is basic |
| Related papers | Yes | Related paper cards and reasons | `/api/papers/{id}/related` | Paper Detail | Topic explorer tests | Navigation aid, not novelty evidence |
| Admin Review | Yes | Review queue, status updates, notes | `/api/admin/*` | Admin Review | Admin tests | Local/demo no-auth workflow |
| Review audit trail | Yes | Review Events table | `/api/admin/review-events` | Admin Review | Admin tests | Not a production compliance system |
| Evaluation Dashboard | Yes | Retrieval/QA/extension/artifact status cards | `/api/evaluation/dashboard` | Evaluation | Evaluation dashboard tests | Missing files show `not_run` |
| Offline/mock provider support | Yes | Works without API keys | `llm_provider`, offline answer/artifact/recommendation providers | Ask, Thesis Extension Finder, Paper Detail | Ask/recommendation/artifact tests | Outputs still need review |
| Optional external provider boundary | Yes | Provider parameter and fallback behavior | Provider abstractions in `intelligence/` | Ask, Thesis Extension Finder, Paper Detail | Fallback behavior covered indirectly | No production external provider integration required |
