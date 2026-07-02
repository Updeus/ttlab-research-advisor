# Demo Script

## Phase 1/2/3/4/5/6 Demo

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
   - no admin review, auth, graph visualization, email, or audio generation.

17. Run the Thesis Extension Finder CLI:

   ```bash
   PYTHONPATH=backend python -m app.intelligence.extension_recommender recommend \
     --interests "RAG, web apps, education" \
     --skills Python React FastAPI \
     --available-time semester \
     --project-type "software prototype" \
     --data-constraints "prefer public or synthetic data" \
     --preferred-difficulty medium \
     --top-k 5 \
     --mode hybrid
   ```

18. Open the Thesis Extension Finder page. Point out:

   - student profile inputs,
   - generated-content notice,
   - ranked paper recommendations,
   - source-supported facts with chunk/page citations,
   - gap support status,
   - proposed extension as a suggestion,
   - MVP scope, stretch goals, required skills, skills gap,
   - data availability, risk, difficulty, implementation time,
   - evaluation plan,
   - potential researcher fit based only on paper authorship.

19. Run extension recommendation evaluation:

   ```bash
   PYTHONPATH=backend python -m app.evaluation.extension_eval --cases data/evaluation/extension_eval_cases.jsonl --top-k 5
   ```

20. Generate Paper Intelligence for five papers:

   ```bash
   PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator batch \
     --limit 5 \
     --types paper_intelligence_bundle podcast_script \
     --provider auto \
     --max-chunks 12
   ```

21. Open a paper with extracted chunks and generated artifacts. Point out:

   - Paper Intelligence section,
   - generated-content notice,
   - public summary and technical summary,
   - contribution and methods,
   - limitations/future work support status,
   - possible extensions marked as system suggestions,
   - required skills and evaluation plan,
   - text-only podcast script,
   - citations with section and page ranges,
   - `needs_review` status,
   - admin review comes later.

22. Run artifact evaluation after replacing placeholder paper IDs with reviewed cases:

   ```bash
   PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval --cases data/evaluation/artifact_eval_cases.jsonl
   ```

23. Run retrieval evaluation only after filling real gold labels:

   ```bash
   PYTHONPATH=backend python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
   ```

24. Run QA evaluation only after filling real gold labels:

   ```bash
   PYTHONPATH=backend python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
   ```

25. Run verification:

   ```bash
   .venv/bin/python -m pytest
   cd frontend && npm run build
   ```

## Talking Point

This is a discovery, extraction, source-chunking, retrieval, citation-grounded Q&A, Thesis Extension Finder, and paper-intelligence milestone. The key Phase 6 talking point is separation: cited source-paper facts are separate from system suggestions, and every generated output remains `needs_review`. Podcast generation is script text only; audio/TTS, admin review, authentication, graph visualization, production email, and deployment remain out of scope.
