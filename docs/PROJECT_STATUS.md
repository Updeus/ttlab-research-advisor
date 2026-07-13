# Project Status

The project has progressed beyond the earlier eight-phase demo description.
Authoritative current status is maintained in
[`FINAL_STATUS.md`](FINAL_STATUS.md); executed methods and evidence are in
[`METHODOLOGY.md`](METHODOLOGY.md) and
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md).

## Current implemented state

- full-paper acquisition/extraction with identity, scan, optional OCR, and
  eligibility diagnostics;
- authoritative complete keyword, feature-hashing, and learned-dense
  representations over 96 eligible papers/719 eligible chunks;
- route-based Search, Ask TTLAB, Thesis Extension Finder, Topic/Author Explorer,
  Evaluation Dashboard, and protected Admin Review;
- transient-by-default public question/profile handling;
- environment-configured reviewer/admin bearer roles and append-only attributed
  review events;
- AI-reviewed retrieval, QA, recommendation, topic/author, section, and
  generated-output evidence; and
- reproducibility, benchmark, sanitized-release, security, privacy,
  accessibility, deployment, and manuscript tooling.

## Evidence-calibrated status

Keyword was the strongest observed held-out retrieval MRR baseline; tuned hybrid
superiority was not demonstrated. The offline answerer produced highly
source-supported extractive claims but low answer-point coverage and no
abstentions on the recorded unanswerable cases. Recommendation improvement over
evidence-only retrieval was not demonstrated. These negative findings are part
of the project result.

No human usefulness/usability study, broad external validation, or production-
scale capacity claim exists. A committed full performance result, complete full
reproduction manifest, final current-commit release bundle/tag, and final
manuscript/PDF closure remain active remediation gates at this snapshot.

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
