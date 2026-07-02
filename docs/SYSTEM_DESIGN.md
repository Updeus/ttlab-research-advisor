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
- `evaluation/retrieval_eval.py` calculates Recall@3, Recall@5, and MRR from manually reviewed gold paper IDs.

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
  -> FastAPI
  -> React dashboard/browser/detail/search view
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

Phase 3 does not call an LLM and does not generate answers.

## Future Extension Points

- `indexing/` can later add production embedding providers and vector-store adapters behind the existing provider interfaces.
- `intelligence/` will hold provider abstractions for grounded answer generation, summaries, extension recommendations, and podcast scripts.
- `evaluation/` will hold retrieval, QA, and summary evaluation modules.
