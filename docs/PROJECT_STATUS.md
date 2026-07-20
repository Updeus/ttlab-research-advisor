# Project Status

The project has progressed beyond the earlier eight-phase demo description.
Authoritative current status is maintained in
[`FINAL_STATUS.md`](FINAL_STATUS.md); executed methods and evidence are in
[`METHODOLOGY.md`](METHODOLOGY.md) and
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md).

## Current implemented state

- full-paper acquisition/extraction with identity, scan, optional OCR, and
  eligibility diagnostics;
- a dedicated-server synchronization worker with a fixed daily timezone
  schedule, overlap lease, new/changed/incomplete processing, persisted run
  history, and protected admin trigger;
- authoritative complete keyword, feature-hashing, and learned-dense
  representations over 96 eligible papers/719 eligible chunks;
- route-based Search, Ask TTLAB, Thesis Extension Finder, Topic/Author Explorer,
  Evaluation Dashboard, and protected Admin Review;
- transient-by-default public question/profile handling;
- environment-configured reviewer/admin bearer roles and append-only attributed
  review events;
- AI-reviewed retrieval, QA, recommendation, topic/author, section, and
  generated-output evidence; and
- a validated 17-stage/102-sample full performance baseline plus
  reproducibility, sanitized-release, security, privacy, accessibility,
  deployment, and manuscript tooling.

## Evidence-calibrated status

Keyword was the strongest observed held-out retrieval MRR baseline; tuned hybrid
superiority was not demonstrated. The offline answerer produced highly
source-supported extractive claims but low answer-point coverage and no
abstentions on the recorded unanswerable cases. Recommendation improvement over
evidence-only retrieval was not demonstrated. These negative findings are part
of the project result.

The independently validated full performance profile completed all 17 required
stages and 102 timed samples with zero failures on WSL2 Linux using an AMD Ryzen
7 5800X, 16 logical CPUs, 4,012,360 KiB visible RAM, and CPU execution. It was a
single-process, concurrency-one local baseline with three cold and three warm
repetitions, not a capacity, scaling, endurance, or production service-level
test.

The external sanity check mapped three pinned CC BY JATS XML documents into the
production chunker contract and returned 3/3 fixed lexical top-one matches. It
did not exercise the main PDF ingestion path and is not cross-domain quality or
broad external-validity evidence. Automated accessibility checks likewise do
not establish WCAG or assistive-technology conformance.

No human usefulness/usability study, broad external validation, or production-
scale capacity claim exists. The current editable sources compile to an
8-Letter-page IEEEtran paper and a 74-A4-page thesis. Their standalone builds
are present; they are not pending research results. Exact-final-commit full
reproduction and the clean sanitized release are fail-loud delivery acceptance
gates executed before tag/push; they rebuild and preflight those documents
rather than inherit success from the earlier benchmark or document build.

## Local demo

```bash
./scripts/run_everything.sh
```

The launcher enables a clearly labeled loopback-only insecure demo bypass.
Production mode remains fail-closed and requires explicit actors, HTTPS base
URL, trusted hosts, and secure CORS origins.

The bounded UI preparation command writes an isolated demo index and must not
support research claims:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo --limit 25
```

See [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for full and distributable
verification paths.
