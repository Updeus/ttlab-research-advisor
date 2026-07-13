# Phase 6 Performance and Scalability Protocol

## Status and evidence boundary

This phase addresses RQ5: **To what extent is the bounded artefact reproducible
and reviewable on documented local hardware, externally format-compatible,
and governed by privacy-minimizing, authenticated, accessible evidence
interfaces without redistributing restricted PDFs?**

Performance is measured by
`backend/app/evaluation/performance_benchmark.py`. The intended versioned raw
result path is
`artifacts/phase6/performance/performance_full_results.json`; a bounded
engineering run may additionally be stored as `performance_quick_results.json`.
The authoritative full result is complete and its independent validation is
`artifacts/phase6/performance/performance_validation.json`. The validator
accepted all 17 stages, 102 timed samples, 102 maximum-RSS records, and zero
failures. The result SHA-256 is
`8642812aa50891c533d238a6ca5f3b6d7870d96ff8c1cf303d8ef9075cbed01e`;
its validation-record SHA-256 is
`c6ff67a680caccdf0fd518fbf1fd5b13f64a8498dcc3e483ca16fb94278bee43`.

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
| OCR extraction | A separate stage processes only eligible papers whose frozen metadata records completed OCR; it reports zero applicable units when the frozen corpus used no OCR. No invented OCR latency is emitted. |
| Chunking | Persisted extracted JSON re-chunked in memory with the production chunker. |
| Indexing | Full eligible chunk set rebuilt for SQLite FTS, feature hashing, and the pinned dense encoder. Output files and DB copies are temporary. |
| Retrieval | Six fixed queries executed in keyword, feature-hashing, learned-dense, and hybrid modes at `top_k=10`. |
| Answering | Three fixed questions answered by the deterministic offline extractive provider without persistence. |
| Recommendation | Three synthetic student profiles processed by the deterministic finder without persistence. |
| API | Seven read-only endpoints exercised through FastAPI TestClient against a disposable DB copy. |
| Frontend build | TypeScript/Vite production build. |
| Frontend page load | Eight primary routes rendered in Playwright Chromium at 1440 by 900 pixels, waiting for network idle and a visible `main` landmark. |

The controller dispatches one probe process at a time. Dense numerical kernels
may still use the recorded PyTorch/OpenMP worker-thread configuration. This is
a latency and resource baseline, not a capacity, saturation, endurance, or
multi-user load test.

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
database hash, Git commit, clean start/end source state, installed Python
packages, Python/npm lock hashes, Tectonic/Playwright/Chromium/tool versions,
and benchmark-script hash are embedded in the result.

The controller atomically replaces a `schema_version: 2` JSON checkpoint after
every completed stage. An interrupted run remains visibly `status:
in_progress`; `--resume` is accepted only when the complete source, corpus,
configuration, hardware, resolved-environment, and lock provenance match. The
independent validator rejects a partial profile, a missing/reordered stage,
anything other than three cold and three warm samples per stage, any failed
sample, summary/sample disagreement, dirty or changed source boundaries,
invalid provenance hashes, or absolute local command paths.
Each successful sample must also match its stage-specific unit count and detail
contract (such as response/content fingerprints for discovery, indexed chunk
counts, provider dimensions/model provenance, fixed query/endpoint counts, and
eight rendered routes). The browser probe chooses unused loopback ports,
requires Vite `--strictPort`, verifies the spawned API service identity, and
rejects an unrelated pre-existing service.

Three repetitions provide only a coarse p95 estimate. It is retained to meet
the bounded local-study constraint and must not be presented as a production
service-level objective.

## Executed full-profile result

The run executed from clean detached commit
`5ccf22ec39cb33bf179cdff6954bfc9e0ce8dbc4`. Its start and end source records
are identical and clean. The integrity-checked SQLite snapshot remained
17,256,448 bytes with SHA-256
`a8153f53fec2e97b6c9cdb31d2ab061e7e825eddfc550f9581a0903d170f35b4`
at both boundaries; it contained 134 catalogue rows, 96 eligible papers, 96
eligible PDFs, 735 raw chunks, 719 eligible chunks, and no OCR-completed paper.
The path-independent backup/integrity record is
`artifacts/phase6/reproduction/database_snapshot_validation.json`; five
read-only integrity/count opens and a six-query keyword probe preserved the
snapshot hash and created no WAL/SHM sidecars before measurement.
The complete provenance hash is
`61378b9aa78ae1c25a1172d62c8501b7603106d3c98142e8370c6c51fa282e8a`.

The recorded host was WSL2 Linux on an AMD Ryzen 7 5800X with 16 logical CPUs,
4,012,360 KiB visible RAM, CPU execution, Python 3.12.3, Node 20.20.2, and npm
10.8.2. The controller dispatched one probe process at a time; PyTorch reported
eight intra-op and 16 inter-op threads. Times below are seconds. Peak RSS is
the larger cold/warm process maximum in MiB. “Failures” is failed attempts out
of the six cold-plus-warm attempts.

| Stage | Units/run | Cold median | Cold p95 | Warm median | Warm p95 | Peak RSS MiB | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| Discovery | 59 | 3.240 | 3.917 | 0.970 | 2.833 | 65.2 | 0/6 |
| Import | 134 | 5.515 | 5.538 | 2.099 | 4.969 | 104.8 | 0/6 |
| PDF extraction | 96 | 15.466 | 15.917 | 12.874 | 14.993 | 112.6 | 0/6 |
| OCR extraction | N/A (0) | 2.633 | 2.838 | 0.151 | 2.294 | 90.1 | 0/6 |
| Chunking | 96 | 10.404 | 10.773 | 8.280 | 9.853 | 62.5 | 0/6 |
| Keyword index | 719 | 2.281 | 2.290 | 0.457 | 2.078 | 89.0 | 0/6 |
| Feature-hashing index | 719 | 2.869 | 2.900 | 0.978 | 2.602 | 96.5 | 0/6 |
| Dense index | 719 | 145.005 | 145.020 | 66.169 | 134.066 | 751.5 | 0/6 |
| Keyword retrieval | 6 | 9.809 | 10.126 | 8.091 | 9.526 | 111.8 | 0/6 |
| Feature-hashing retrieval | 6 | 10.323 | 10.369 | 8.137 | 10.176 | 102.7 | 0/6 |
| Dense retrieval | 6 | 84.487 | 86.265 | 12.215 | 78.342 | 563.5 | 0/6 |
| Hybrid retrieval | 6 | 93.355 | 93.616 | 20.326 | 86.385 | 568.9 | 0/6 |
| Offline answering | 3 | 83.355 | 83.736 | 9.842 | 75.800 | 571.9 | 0/6 |
| Offline recommendation | 3 | 83.604 | 85.675 | 10.482 | 76.668 | 562.6 | 0/6 |
| ASGI API | 7 | 79.606 | 81.178 | 3.948 | 72.397 | 641.2 | 0/6 |
| Frontend build | 1 | 31.145 | 33.201 | 30.763 | 31.270 | 461.2 | 0/6 |
| Frontend page load | 8 | 12.496 | 12.807 | 12.463 | 12.631 | 458.2 | 0/6 |

Dense indexing was the slowest and highest-memory measured stage. The large
gap between warm medians and warm p95 for model-dependent stages reflects the
first warm-series repetition loading the model, followed by cached repetitions;
with only three observations, that p95 must not be treated as a stable tail
estimate. Frontend page-load time is the sum across eight routes; cold median
per-route values ranged from 1.122 seconds (`/admin`) to 2.976 seconds
(`/explorer`). The zero-unit OCR row measures only probe/process overhead and
is not an OCR-latency claim.

The measured Python environment contained 96 resolved packages. The tracked
lock also includes `pytesseract==0.3.13`, which was absent during measurement;
because the frozen corpus had zero OCR units, no OCR work was timed. After the
benchmark sealed, that one package—and no other package change—was added. The
post-run lock validator now confirms all 92 exact pins, reports five additional
document-inspection packages, and is stored at
`artifacts/phase6/reproduction/python_environment_validation.json`.

## Safe execution

Run the bounded profile and validate its two selected stages:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.performance_benchmark \
  --profile quick \
  --repetitions 3 \
  --database data/papers.db \
  --runtime-root . \
  --out artifacts/phase6/performance/performance_quick_results.json \
  --stage import --stage frontend_build
PYTHONPATH=backend .venv/bin/python -m app.evaluation.performance_validator \
  artifacts/phase6/performance/performance_quick_results.json \
  --expected-profile quick --expected-repetitions 3 \
  --stage import --stage frontend_build
```

Run the full authoritative profile from a clean source state:

```bash
make benchmark
```

If the controller stops after writing a valid checkpoint, resume the identical
run with:

```bash
make benchmark-resume
```

Both full targets finish by running `make performance-validate`; a nonzero
stage failure cannot be copied or cited as authoritative evidence.

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
