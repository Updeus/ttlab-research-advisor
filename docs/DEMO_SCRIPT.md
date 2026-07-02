# Demo Script

## Phase 1/2 Demo

1. Show the project scaffold:

   ```bash
   find backend frontend data docs -maxdepth 2 -type d | sort
   ```

2. Discover TTLAB publications:

   ```bash
   PYTHONPATH=backend python -m app.ingestion.ttlab_page discover \
     --url https://lab.tt/index.php/category/pub/ \
     --max-pages 2 \
     --out data/seed/ttlab_publications_discovered.json
   ```

3. Inspect the seed JSON:

   ```bash
   python -m json.tool data/seed/ttlab_publications_discovered.json | head -80
   ```

4. Import discovered records:

   ```bash
   PYTHONPATH=backend python -m app.ingestion.manual_import \
     --seed data/seed/ttlab_publications_discovered.json
   ```

5. Start the backend:

   ```bash
   uvicorn app.main:app --reload --app-dir backend
   ```

6. Start the frontend:

   ```bash
   cd frontend
   npm run dev
   ```

7. Download the first 10 direct PDFs:

   ```bash
   PYTHONPATH=backend python -m app.ingestion.pdf_downloader --from-db --limit 10 --download
   ```

8. Extract the first 10 downloaded PDFs:

   ```bash
   PYTHONPATH=backend python -m app.ingestion.pdf_parser extract --limit 10
   ```

9. Chunk the first 10 extracted papers:

   ```bash
   PYTHONPATH=backend python -m app.indexing.chunker chunk --limit 10
   ```

10. Open the dashboard, paper browser, and paper detail view. Point out:

   - imported paper count,
   - direct PDF URL count,
   - downloaded/extracted PDF counts,
   - total chunks,
   - extraction diagnostics,
   - chunk previews with page ranges,
   - review-needed status,
   - source/PDF/TTLAB post links.

11. Run verification:

   ```bash
   python -m pytest
   cd frontend && npm run build
   ```

## Talking Point

This is a discovery, extraction, and source-chunking milestone. It intentionally stops before RAG, summaries, podcast generation, vector search, and extension recommendations so later AI features are grounded in auditable paper records and page-aware chunks.
