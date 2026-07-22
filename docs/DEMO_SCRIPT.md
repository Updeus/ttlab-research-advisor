# Evidence-Calibrated Demo Script

## Setup

Use the loopback launcher:

```bash
./scripts/run_everything.sh --skip-downloads
```

For a bounded UI-only dataset:

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.prepare_demo \
  --limit 25 --skip-downloads
```

The bounded feature-hashing index is isolated and is not research evidence.
The launcher enables a visibly insecure loopback-only admin bypass; do not
present it as production authentication.

## Seven-to-ten-minute flow

1. **Dashboard and readiness (45 seconds).** Show the corpus boundary, eligible
   versus unavailable/excluded records, keyword/feature-hashing/dense index
   coverage, freshness, review queue, and evaluation availability. State that
   719/719 is index integrity, not search accuracy.
2. **Paper Browser and Detail (60 seconds).** Open an eligible paper. Show source
   metadata, PDF/title state, page extraction diagnostics, OCR status, chunk
   page/section/snippet, and review state. Unknown fields/sections are not
   invented.
3. **Search (60 seconds).** Compare `keyword`, `feature hashing`, and `dense` for
   a query such as `mobile network optimization`. Explain that feature hashing
   is a lexical-feature baseline. Mention the held-out negative result: keyword
   led MRR and tuned hybrid did not demonstrate superiority.
4. **Ask TTLAB (60 seconds).** Ask a bounded question. Point out provider/model,
   timestamp, generated notice, paper/chunk/page citations, retrieved passages,
   and partial/unsupported warnings. State that runtime `grounded` is not a
   correctness label and that the offline QA study found low answer-point
   coverage and failed unanswerable abstentions.
5. **Idea Generator (90 seconds).** Confirm that the approved default Ollama
   model is ready, then describe interests and skills conversationally. Show the
   coaching response, idea cards, MVP, skills, evaluation method, and any related
   paper background. Follow up with “make the first idea smaller.” Explain that
   no-match prompts still receive general suggestions, conversations are not
   saved, paper links are inspiration rather than novelty evidence, and an
   Ollama outage produces a retry state rather than another-provider fallback.
6. **Paper intelligence (60 seconds).** Show a cited bundle and text podcast
   script. Identify `ai_reviewed` versus `needs_reprocess`, support labels, and
   suggestions. There is no audio/TTS.
7. **Topic/Author Explorer (60 seconds).** Show controlled labels and source-
   derived author links. Explain that public lexical labels favor precision and
   inspectability; author links do not imply availability, endorsement, or
   suitability.
8. **Evaluation (60 seconds).** Show executed retrieval, QA, recommendation,
   and topic evidence and confidence intervals. Point out negative results and
   explain that AI silver/proxy review is not human validation.
9. **Admin Review (45 seconds).** Show the demo-security notice, authenticated
   production boundary, review status, actor attribution, and hash-chained event
   trail. Do not change an item unless the demo state is disposable.
10. **Close (30 seconds).** Summarize the contribution as integration,
    traceability, evidence discipline, and reproducible offline
    characterization—not a novel algorithm or proven human advisor.

## Suggested queries

- `Which indexed papers apply retrieval-augmented generation?`
- `What methods are used for agricultural monitoring?`
- `mobile network pricing optimization`
- Extension profile: interests `RAG, web applications`; skills `Python,
  FastAPI, React`; time `semester`; data `public preferred`; difficulty
  `medium`.

## Evidence to keep visible

- frozen snapshot: 96 eligible papers/719 eligible chunks;
- source paper, chunk, page/section, and snippet;
- retrieval mode/provider and index freshness;
- generated, inferred, paper-stated, and suggestion labels;
- review status/type and security mode;
- measured value versus `not_run`; and
- privacy notice for question/profile fields.

## Do not claim

- comprehensive TTLAB archive coverage;
- human-tested usefulness or supervisor approval;
- hybrid retrieval superiority;
- factual correctness from a citation badge;
- learned semantics from feature hashing;
- researcher availability or broad expertise;
- OCR quality, full performance/scalability, or production readiness from the
  current committed evidence; or
- that a local demo bypass is acceptable for public deployment.

## Pre-demo verification

```bash
PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check
PYTHONPATH=backend .venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Use current live routes/data. Never use test fixtures as screenshot or metric
evidence.
