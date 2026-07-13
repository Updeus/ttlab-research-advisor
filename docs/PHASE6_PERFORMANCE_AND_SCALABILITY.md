# Phase 6 Performance and Scalability Protocol

## Status and evidence boundary

Performance is measured by
`backend/app/evaluation/performance_benchmark.py`. The intended versioned raw
result path is
`artifacts/phase6/performance/performance_full_results.json`; a bounded
engineering run may additionally be stored as `performance_quick_results.json`.
No full result is committed at this documentation snapshot. Consequently, no
paper/thesis performance or scalability claim is currently supported. Only a
validated full-corpus result may close that evidence gate.

The benchmark does not infer retrieval quality from latency. Quality results
come from the separate source-reviewed evaluation sets. A successful test or
fast response is not evidence that an answer is correct or useful.

## Workloads

The harness covers the required operations independently:

| Stage | Unit and workload |
|---|---|
| Discovery | Records parsed from one live TTLAB publication archive page; network and server latency are included. |
| Import | Seed records inserted into a fresh disposable SQLite database. |
| PDF extraction | Authorized local PDFs processed into a temporary directory without OCR. |
| OCR | Reported as not applicable when the frozen corpus has zero OCR-completed papers/pages. No invented OCR latency is emitted. |
| Chunking | Persisted extracted JSON re-chunked in memory with the production chunker. |
| Indexing | Full eligible chunk set rebuilt for SQLite FTS, feature hashing, and the pinned dense encoder. Output files and DB copies are temporary. |
| Retrieval | Six fixed queries executed in keyword, feature-hashing, learned-dense, and hybrid modes at `top_k=10`. |
| Answering | Three fixed questions answered by the deterministic offline extractive provider without persistence. |
| Recommendation | Three synthetic student profiles processed by the deterministic finder without persistence. |
| API | Seven read-only endpoints exercised through FastAPI TestClient against a disposable DB copy. |
| Frontend build | TypeScript/Vite production build. |
| Frontend page load | Eight primary routes rendered in Playwright Chromium at 1440 by 900 pixels, waiting for network idle and a visible `main` landmark. |

All workloads use concurrency one. This is a latency and resource baseline, not
a capacity, saturation, endurance, or multi-user load test.

## Repetition and summaries

Each full profile uses three process-cold and three warm repetitions. A cold
repetition uses a fresh Python process. A warm series runs sequentially within
one process; the browser series also reuses one browser context. The operating
system page cache is deliberately not flushed, so “cold” means process-cold,
not machine-cold.

Raw elapsed time, processed units, seconds per unit, status, and bounded failure
information are retained for every repetition. The report calculates median
and linearly interpolated p95 over successful repetitions, while failure rate
uses all attempts. GNU `time` records process maximum resident set size in KiB
where available. Hardware, runtime versions, corpus counts, concurrency,
database hash, Git commit, and dirty-worktree state are embedded in the result.

Three repetitions provide only a coarse p95 estimate. It is retained to meet
the bounded local-study constraint and must not be presented as a production
service-level objective.

## Safe execution

Run the bounded profile:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.performance_benchmark \
  --profile quick \
  --database data/papers.db \
  --out artifacts/phase6/performance/performance_quick_results.json
```

Run the full authoritative profile:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.performance_benchmark \
  --profile full \
  --database data/papers.db \
  --out artifacts/phase6/performance/performance_full_results.json
```

Index builds write only to temporary paths and disable chunk-status updates.
Keyword indexing and APIs operate on byte copies of the DB. Answer and
recommendation probes explicitly set `persist=False`. The live recommendation
and answer histories therefore remain unchanged.

## External-validity sanity check

`backend/app/evaluation/external_sanity.py` uses the official Europe PMC
Articles RESTful API to reacquire three pinned full-text XML articles. Every
response must contain its expected PMCID/title and machine-verifiable CC BY
license URL before it is processed. The documents are chunked with the project
chunker and tested with three fixed lexical-discrimination queries.

Europe PMC documents that its full-text XML endpoint as serving its Open Access
subset and warns that individual license terms still govern reuse:
[developer API](https://europepmc.org/RestfulWebService) and
[open-access subset policy](https://europepmc.org/downloads/openaccess).

The raw XML cache is ignored and excluded from the release. The committed
manifest retains official identifiers, titles, DOI where present, CC BY URL,
file hash, counts, acquisition status, and smoke-check result. This check only
demonstrates JATS-format compatibility and trivial lexical discrimination on
three life-science documents. It is not TTLAB evidence, a cross-domain quality
evaluation, or proof of broad external validity.

## Threats to validity

- Remote discovery latency includes uncontrollable network and TTLAB-server
  conditions.
- OS caches, background processes, WSL/host scheduling, and thermal behavior
  are not controlled.
- Maximum RSS is process-level and cannot isolate shared libraries or the OS
  file cache.
- ASGI TestClient excludes network, TLS, reverse-proxy, and browser latency;
  those responsibilities remain deployment-specific.
- The frontend uses one Chromium engine, viewport, host, and local network.
- The source corpus is small and single-laboratory; asymptotic or production
  scaling is not established.
- The external sanity corpus is three CC BY life-science articles, not a
  representative sample of scholarship.
