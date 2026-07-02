# System Design

## Backend

The backend is a FastAPI application under `backend/app`.

- `main.py` creates the app, CORS policy, startup table creation, and health endpoint.
- `db.py` configures SQLite and SQLModel sessions.
- `models/` defines `Paper`, `Author`, and `Chunk`.
- `api/papers.py` exposes Phase 1 read endpoints.
- `ingestion/ttlab_page.py` discovers TTLAB archive records.
- `ingestion/manual_import.py` imports seed JSON into SQLite.
- `ingestion/pdf_downloader.py` safely downloads direct PDFs only when `--download` is passed.

## Data Flow

```text
TTLAB WordPress archive
  -> discovery CLI
  -> data/seed/ttlab_publications_discovered.json
  -> data/seed/papers.json
  -> manual import CLI
  -> SQLite
  -> FastAPI
  -> React dashboard/browser
```

## Discovery Contract

Each discovered record includes:

```text
paper_id, title, authors, year, publication_date_raw, venue,
post_url, source_url, pdf_url, local_pdf_path, topics, all_urls,
ingestion_status, pdf_text_status, review_status, raw_scraped
```

The scraper resolves relative URLs, deduplicates by normalized title and URLs, preserves raw scraped paragraphs/links, and does not follow external publisher pages.

## Future Extension Points

- `indexing/` will hold chunking, keyword search, embeddings, and vector-store adapters.
- `intelligence/` will hold provider abstractions for grounded answer generation, summaries, extension recommendations, and podcast scripts.
- `evaluation/` will hold retrieval, QA, and summary evaluation modules.
