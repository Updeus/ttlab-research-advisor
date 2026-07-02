# System Design

## Backend

The backend is a FastAPI application under `backend/app`.

- `main.py` creates the app, CORS policy, startup table creation, and health endpoint.
- `db.py` configures SQLite and SQLModel sessions.
- `models/` defines `Paper`, `Author`, and `Chunk`.
- `api/papers.py` exposes paper, stats, extraction, chunk, and simple chunk keyword endpoints.
- `ingestion/ttlab_page.py` discovers TTLAB archive records.
- `ingestion/manual_import.py` imports seed JSON into SQLite.
- `ingestion/pdf_downloader.py` safely downloads direct PDFs only when `--download` is passed.
- `ingestion/pdf_parser.py` extracts PDF text page-by-page using PyMuPDF.
- `indexing/chunker.py` creates deterministic page-aware source chunks from extracted text.
- `indexing/keyword_search.py` creates/searches a SQLite FTS5 keyword index, with deterministic fallback matching.
- `indexing/embedder.py` builds local hashing embeddings without API keys or model downloads.
- `indexing/vector_store.py` loads local embedding JSON and performs cosine search.
- `indexing/retriever.py` combines keyword and semantic results for hybrid retrieval.
- `intelligence/llm_provider.py` defines the offline extractive provider and optional external-provider adapter boundary.
- `intelligence/rag_answerer.py` retrieves chunks, drafts an answer, verifies citations, and stores answers.
- `intelligence/citation_verifier.py` checks citation presence and lightweight lexical support.
- `evaluation/retrieval_eval.py` calculates Recall@3, Recall@5, and MRR from manually reviewed gold paper IDs.
- `evaluation/qa_eval.py` runs Ask TTLAB and records citation/grounding outputs against manually reviewed labels.

## Data Flow

```text
TTLAB WordPress archive
  -> discovery CLI
  -> data/seed/ttlab_publications_discovered.json
  -> data/seed/papers.json
  -> manual import CLI
  -> SQLite
  -> PDF downloader
  -> data/pdfs/{paper_id}.pdf
  -> PDF parser
  -> data/extracted_text/{paper_id}.json + .txt
  -> deterministic chunker
  -> data/chunks/{paper_id}.json + SQLite chunk rows
  -> keyword index + hashing vector index
  -> retrieval API
  -> Ask TTLAB answerer + citation verifier
  -> FastAPI
  -> React dashboard/browser/detail/search/Ask view
```

## Discovery Contract

Each discovered record includes:

```text
paper_id, title, authors, year, publication_date_raw, venue,
post_url, source_url, pdf_url, local_pdf_path, topics, all_urls,
ingestion_status, pdf_text_status, review_status, raw_scraped
```

The scraper resolves relative URLs, deduplicates by normalized title and URLs, preserves raw scraped paragraphs/links, and does not follow external publisher pages.

## Extraction Contract

Each extraction JSON includes:

```text
paper_id, local_pdf_path, page_count, pages[], full_text_path,
text_hash, extraction_status, warnings, diagnostics
```

Diagnostics include page/word/character counts, pages with and without text, possible scanned-PDF detection, and extraction errors.

## Chunk Contract

Each chunk includes:

```text
chunk_id, paper_id, chunk_index, page_start, page_end, section,
text, char_count, word_count, token_count_estimate, source_hash
```

Chunks are deterministic, page-aware, overlap by roughly 100-150 words, and use simple heading rules for section labels.

## Retrieval Contract

Retrieval returns source chunks only:

```text
rank, paper_id, paper_title, authors, year, chunk_id,
section, page_start, page_end, snippet, scores, source
```

Modes:

- `keyword`: SQLite FTS5 if available; fallback token matching otherwise.
- `semantic`: local hashing embeddings stored under `data/indexes/`.
- `hybrid`: normalized keyword and semantic score combination.

Phase 3 retrieval does not call an LLM and does not generate answers.

## Ask Contract

Ask TTLAB returns stored, source-cited answer drafts:

```text
answer_id, question, answer, grounding_status, provider, model,
retrieval_mode, citations[], retrieved_chunks[], warnings[], created_at
```

Grounding status:

- `grounded`: citations map to retrieved chunks and the answer overlaps with cited snippets.
- `partial`: some support exists but citations or overlap are weak.
- `unsupported`: no useful retrieved/cited support exists.

The default provider is `offline_extractive`, which works without API keys by extracting relevant sentences from retrieved chunks. Optional external providers must be adapter-based and must not break offline operation.

## Future Extension Points

- `indexing/` can later add production embedding providers and vector-store adapters behind the existing provider interfaces.
- `intelligence/` can later add production answer providers, summaries, extension recommendations, and podcast scripts behind separate boundaries.
- `evaluation/` will hold retrieval, QA, and summary evaluation modules.
