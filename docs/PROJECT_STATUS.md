# Project Status

The project has progressed beyond the earlier eight-phase demo description.
Authoritative current status is maintained in
`docs/peer_review_readiness/FINAL_READINESS_REPORT.md`; executed methods and evidence are in
[`METHODOLOGY.md`](METHODOLOGY.md) and
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md). `FINAL_STATUS.md` is a
superseded historical-v1 checkpoint, not current checkout status.

## Current implemented state

- full-paper acquisition/extraction with identity, scan, optional OCR, and
  eligibility diagnostics;
- operator-run corpus staging with deterministic generation manifests; the
  scheduled worker and protected trigger fail closed until a whole-snapshot
  atomic promotion exists;
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

The following outcomes are retained historical-v1 AI-assisted evidence, not
measurements of the remediated current runtime or prospective v2 protocol.
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
scale capacity claim exists. The editable paper and thesis satisfy the local
six-page-maximum and 75-page-minimum manuscript gates; the exact page and
reference counts belong to the final candidate report rather than this
long-lived status overview. Full reproduction and the clean sanitized release
bind the source-candidate commit/tree they actually execute. The later evidence
commit records validated outputs and attestations but is not relabeled as the
reproduced source; any source, protocol, case, application, or manuscript change
requires a fresh candidate run. These fail-loud gates rebuild and preflight the
documents rather than inherit success from an earlier benchmark or standalone
document build.

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
