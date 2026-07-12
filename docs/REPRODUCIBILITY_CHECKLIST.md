# Reproducibility Checklist

Use this from a fresh clone to recreate a **bounded local UI demo**, not the
research snapshot or reported experiments. The audited helper can produce a
partial vector index; full research reproduction is being implemented under
`REP-01` in `docs/REVIEW_REMEDIATION_MATRIX.md`.

## 1. Clone And Backend Setup

```bash
git clone https://github.com/Updeus/ttlab-research-advisor.git
cd ttlab-research-advisor

python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

## 2. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

## 3. Seed Data

The repo includes seed JSON under `data/seed/`.

Import seed data:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.manual_import \
  --seed data/seed/ttlab_publications_discovered.json
```

If seed data needs to be refreshed from TTLAB:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.ttlab_page discover \
  --url https://lab.tt/index.php/category/pub/ \
  --max-pages 2 \
  --out data/seed/ttlab_publications_discovered.json
```

## 4. Prepare Demo Data

Recommended one-command local prep:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

Manual equivalent:

```bash
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_downloader --from-db --limit 25 --download
PYTHONPATH=backend .venv/bin/python -m app.ingestion.pdf_parser extract --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.chunker chunk --limit 25
PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild
PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider hashing
PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild
PYTHONPATH=backend .venv/bin/python -m app.intelligence.paper_artifact_generator batch \
  --limit 5 \
  --types paper_intelligence_bundle podcast_script \
  --provider auto \
  --max-chunks 12
```

The helper does not process all papers by default. It must use an isolated demo
index and must never be cited as evidence of full-corpus coverage.

## 5. Run The App

Backend:

```bash
uvicorn app.main:app --reload --app-dir backend
```

Frontend:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

## 6. Evaluation

Evaluation files under `data/evaluation/` are placeholders/templates unless manually reviewed.

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_eval --questions data/evaluation/questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.qa_eval --questions data/evaluation/qa_questions.jsonl --mode hybrid --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.extension_eval --cases data/evaluation/extension_eval_cases.jsonl --top-k 5
PYTHONPATH=backend .venv/bin/python -m app.evaluation.artifact_eval --cases data/evaluation/artifact_eval_cases.jsonl
PYTHONPATH=backend .venv/bin/python -m app.evaluation.run_all
```

Automatic metrics only measure against the provided gold/test files. Human review templates are provided for manual thesis evaluation.

## 7. Testing

Backend:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
```

Frontend build:

```bash
cd frontend
npm run build
```

Smoke check:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
```

## 8. Troubleshooting

- Missing `pytest`: activate `.venv`, then run `python -m pip install -r backend/requirements.txt`.
- Missing `.venv`: create it with `python -m venv .venv`.
- Missing local SQLite DB: run seed import or `app.demo.prepare_demo`.
- No PDFs downloaded: direct PDF links may be unavailable or network may be down; the app still demos metadata/search if chunks already exist locally.
- Semantic index missing: run `PYTHONPATH=backend .venv/bin/python -m app.indexing.embedder index --provider hashing`.
- Keyword index missing: run `PYTHONPATH=backend .venv/bin/python -m app.indexing.keyword_search rebuild`.
- Topic explorer empty: run `PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild`.
- Evaluation files not run: the Evaluation Dashboard will show `not_run`; this is expected until evaluators are run with reviewed cases.
- CORS/API base URL issue: frontend defaults to `http://127.0.0.1:8000`; the backend allows both `http://localhost:5173` and `http://127.0.0.1:5173`.

## 9. Git Hygiene

Do not commit generated local artifacts:

- `data/pdfs/`
- `data/extracted_text/`
- `data/chunks/`
- `data/indexes/`
- `data/generated/`
- SQLite DB files
- evaluation result JSON
