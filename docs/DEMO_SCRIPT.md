# Demo Script

## Phase 1/2/3/4 Demo

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

11. Rebuild keyword search:

   ```bash
   PYTHONPATH=backend python -m app.indexing.keyword_search rebuild
   ```

12. Build local semantic index:

   ```bash
   PYTHONPATH=backend python -m app.indexing.embedder index --provider hashing --limit 10
   ```

13. Test hybrid retrieval:

   ```bash
   PYTHONPATH=backend python -m app.indexing.retriever search "RAG academic research" --mode hybrid --top-k 5
   ```

14. Open the Search page. Point out:

   - keyword / semantic / hybrid modes,
   - source chunk snippets,
   - paper title/authors/year,
   - section and page range,
   - source/PDF links,
   - no generated answer text.

15. Ask TTLAB from the CLI:

   ```bash
   PYTHONPATH=backend python -m app.intelligence.rag_answerer ask "Which TTLAB papers discuss RAG?" --mode hybrid --top-k 5
   ```

16. Open the Ask TTLAB page. Point out:

   - generated-answer notice,
   - grounding status,
   - citations with paper title and page ranges,
   - retrieved chunk snippets,
   - source/PDF links,
   - no Thesis Extension Finder, summaries, or podcast features.

17. Run retrieval evaluation only after filling real gold labels:

   ```bash
   PYTHONPATH=backend python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
   ```

18. Run QA evaluation only after filling real gold labels:

   ```bash
   PYTHONPATH=backend python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
   ```

19. Run verification:

   ```bash
   python -m pytest
   cd frontend && npm run build
   ```

## Talking Point

This is a discovery, extraction, source-chunking, retrieval, and citation-grounded Q&A milestone. It intentionally stops before summaries, podcast generation, admin review, and extension recommendations so later features remain grounded in auditable paper records and page-aware chunks.
