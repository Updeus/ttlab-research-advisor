# Local Ollama Provider Boundary

Ollama is an optional local answer composer for the TTLAB Research
Intelligence Platform. Retrieval and public-source eligibility are decided
before model invocation. The default and reproducible path remains the
deterministic `offline_extractive` provider; a fluent model response does not
change citation, publication, rights, or review status.

Source-traceable means that an answer retains paper/chunk/page evidence and
generation provenance. It does not establish factual correctness, semantic
entailment, completeness, novelty, or human review. The automatic claim checker
therefore stops at `support_unverified`.

## Evidence status

The configured model registry and pull candidates are unranked inventory
suggestions. No committed benchmark establishes a green/yellow/red quality
tier, hardware fit, answer benefit, or preferred model. The historical QA run
found the local service unavailable and consequently reports no Ollama answer-
quality, latency, quantization, or comparative result. `GET
/api/llms/benchmark/latest` returns `not_run` when no local benchmark file
exists.

## Required model identity configuration

Ollama tags are mutable, so enabling the provider requires both the provider
allowlist and an operator-supplied exact digest for each permitted tag:

```bash
export TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive", "ollama"]'
export TTLAB_OLLAMA_ALLOWED_MODEL_DIGESTS='{"qwen3:4b-instruct-2507-q4_K_M":"<64-hex-sha256>"}'
```

Obtain the digest from the operator-controlled Ollama service and verify it
against the locally installed artifact. Do not copy the placeholder above. An
unlisted tag, missing model, digest mismatch, changed response tag, or tag whose
digest changes during generation fails to the explicitly recorded offline
provider.

Before a generation request the provider checks `/api/tags`; it checks the tag
again after the response. The standard Ollama generation response may identify
the tag without reporting its immutable digest. In that common case the output
is attributed to the mutable tag and records
`generation_time_digest_verified=false`, even when both surrounding checks
match. Those checks reduce the interval in which a tag swap can go unnoticed;
they are not proof of the exact model bytes used during generation. Only a
response-reported matching digest permits a digest-bound effective model
identity.

Public status output lists only installed models whose reported digest matches
the configured allowlist. Internal provider URLs and raw connection errors are
redacted. Configuration readiness is not a quality benchmark.

## Runtime defaults

The provider uses bounded settings intended for a local demonstration:

- `num_ctx=4096`;
- bounded `num_predict` derived from the answer word limit;
- temperature `0.1`;
- `keep_alive=10m`; and
- retrieved context only, after the public/technical scope decision.

Query expansion, metadata and section scoring, evidence weighting, and
diversity are retrieval heuristics. The model cannot declare its own answer
grounded or override the pre-generation answerability gate. Citation pruning
retains only sources referenced by the composed answer, and provenance records
the requested, configured, and effective provider/model plus any fallback.

## API use

Inspect the redacted status first:

```bash
curl http://127.0.0.1:8000/api/llms/local
curl http://127.0.0.1:8000/api/llms/benchmark/latest
```

Ask through the public projection:

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Which publicly approved TTLAB papers discuss RAG?",
    "mode": "keyword",
    "top_k": 5,
    "audience": "student",
    "max_words": 250,
    "provider": "ollama",
    "model": "qwen3:4b-instruct-2507-q4_K_M"
  }'
```

The public endpoint is transient and cannot select technical/evaluation scope.
If no papers have the independent publication, rights, searchable-access,
extraction-review, and current-generation approvals, the correct response is a
governed empty/abstention state rather than technical-corpus fallback.

The local launcher checks Ollama when available:

```bash
./scripts/run_everything.sh --serve-only
./scripts/run_everything.sh --serve-only --no-ollama
```

The second form intentionally exercises the offline path. The insecure demo
admin bypass remains loopback-only and is unrelated to provider identity.

## Optional local benchmark

An operator with an allowlisted, digest-matched service may run:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation.ollama_benchmark --models installed
```

The generated JSON/CSV files are local and ignored. Their heuristics and
machine-specific timing are engineering/formative evidence, not human ratings,
semantic entailment, a production service level, or a manuscript result unless
the complete inputs, digest/configuration, raw cases, validator, and limitations
are separately versioned.

## Residual controls

- Keep Ollama on an operator-controlled local/private network endpoint.
- Do not send restricted paper text to an external provider without a separate
  approved privacy, contractual, retention, and rights decision.
- Treat model pull/acquisition and license review as explicit operator actions.
- Do not infer hardware fit from a parameter count or quantization name.
- Preserve fallback warnings and negative/unavailable results rather than
  converting them into a successful model comparison.
