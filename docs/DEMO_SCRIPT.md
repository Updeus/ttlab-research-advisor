# Demo Script

## Phase 1 Demo

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
   PYTHONPATH=backend uvicorn app.main:app --reload
   ```

6. Start the frontend:

   ```bash
   cd frontend
   npm run dev
   ```

7. Open the dashboard and paper browser. Point out:

   - imported paper count,
   - direct PDF URL count,
   - missing PDF count,
   - review-needed status,
   - source/PDF/TTLAB post links.

## Talking Point

This is a discovery and data-foundation milestone. It intentionally stops before RAG, summaries, podcast generation, and extension recommendations so the later AI features are grounded in auditable paper records.
