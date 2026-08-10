# Security Guide

## GCP identity boundary

Managed inference uses Application Default Credentials from the Cloud Run API service identity; API keys are not accepted or configured. Only that identity receives Vertex AI User. The maintenance identity may write corpus/index objects and access Cloud SQL but has no Vertex role; the API has read-only bucket access. Buckets enforce uniform access, public-access prevention, versioning, retention, and lifecycle policy.

Generation telemetry is limited to provider/model/version where returned, region, finish/safety state, token usage, latency, SDK version, hashes of prompts/configuration, and fallback reason. Prompts, questions, retrieved passages, credentials, and raw provider responses must not be logged. Public GCP requests cannot override the server provider or model.

## Security modes

`TTLAB_SECURITY_MODE=local_demo` is the default. It changes documentation and
response labeling, but it does **not** grant anonymous admin access. With no
configured actors, protected routes fail closed with HTTP 401.

An explicitly insecure loopback demo is available only when all of the
following are true:

```bash
export TTLAB_SECURITY_MODE=local_demo
export TTLAB_ALLOW_INSECURE_LOCAL_DEMO=true
```

The bypass is accepted only from a loopback client address and responses expose
`X-TTLAB-Insecure-Demo: true`. Never bind that mode to a public interface, use
it for research results, or describe it as production authentication.
Its actor is typed as a visibly insecure local human administrator so the full
workflow can be demonstrated. It is never accepted outside loopback demo mode.

`TTLAB_SECURITY_MODE=production` fails startup unless:

- at least one active local admin account or admin service actor exists;
- `TTLAB_PUBLIC_BASE_URL` uses HTTPS;
- the public hostname is in `TTLAB_TRUSTED_HOSTS`;
- all CORS origins use HTTPS; and
- insecure local-demo bypass is disabled;
- the API uses `TTLAB_SERVICE_ROLE=api` with in-process synchronization disabled; and
- `TTLAB_API_WORKER_COUNT=1` while the built-in process-local limiter is used.

Interactive OpenAPI/ReDoc endpoints are disabled in production.

## Creating local administrators

Create the first browser administrator before starting production:

```bash
PYTHONPATH=backend .venv/bin/python -m app.admin_cli create jarod --display-name "Jarod"
```

Passwords are Argon2id-hashed. Login is locked for 15 minutes after five failed
attempts. Sessions have an eight-hour idle and 24-hour absolute lifetime and use
Secure, HttpOnly, SameSite cookies. Every cookie-authenticated mutation must also
present the matching CSRF cookie value in `X-CSRF-Token`. Additional admins use a
one-time temporary password created in Admin Control; the account must change it
before administrative mutations. Administrators cannot deactivate themselves or
the final active account.

A successful login also confirms the password for sensitive model, account, and
publication actions for 15 minutes. After that window, the affected dashboard
panel asks for the current password again and refreshes the confirmation window.
The publication authority/rights note is an audit justification, not a password.

## Creating bearer actors

Generate a separate random 256-bit token per actor. Never use a password or a
shared token. The server receives only the digest in environment configuration:

```bash
umask 077
TOKEN="$(openssl rand -hex 32)"
DIGEST="$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)"
printf 'Store this token once in the approved secret manager: %s\n' "$TOKEN"
printf 'Configured digest: %s\n' "$DIGEST"
unset TOKEN
```

Configure actors as a JSON array. This example contains placeholders, not a
working secret:

```bash
export TTLAB_AUTH_ACTORS_JSON='[
  {
    "token_sha256": "<64-character-sha256-digest>",
    "actor_id": "stable-reviewer-id",
    "display_name": "Named Reviewer",
    "role": "reviewer",
    "reviewer_type": "human",
    "active": true
  }
]'
```

Allowed roles are `reviewer` and `admin`; reviewer types are `human`, `ai`, and
`service`. Actor and digest values must be unique. Call protected routes with:

```bash
curl -H "Authorization: Bearer $TTLAB_REVIEWER_TOKEN" \
  https://advisor.example/api/admin/overview
```

Do not put a bearer token in a query string, commit, screenshot, browser local
storage, build argument, or shell history. Use a deployment secret manager and
short, auditable distribution. To revoke or rotate a token, remove/deactivate
the digest, restart all workers, and inspect request/audit logs for the actor.

## Authorization contract

- Public: only explicitly published metadata and rights-cleared/searchable
  source snippets, search, aggregate diagnostics/evaluation, transient Ask, and
  transient Extension Finder. Technical eligibility alone grants no public
  access.
- Reviewer/admin: histories/items containing submitted questions/profiles,
  admin overview/queues/events, the `NOT PUBLIC` publication preview, full
  extracted chunks, one-paper persisted artifact generation, and distinct
  review/correction mutations.
- Human admin only: administrative approval/rejection and publication/rights/
  access decisions. Batch artifact generation requires the `admin` role
  (including an explicitly labeled demo service actor).
- AI reviewer: must record `ai_reviewed`; it cannot represent human review or
  administrative approval.

Every review event records the stable actor, reviewer type/role, server request
ID, change diff, timestamp, previous event hash, and its own hash. SQLite blocks
event updates/deletes. This is application/database-process immutability, not a
claim that a machine/database owner cannot rewrite the SQLite file.

Any metadata, generated-artifact, or recommendation correction is a new
reviewable version and is therefore forced back to `needs_review`. Correction
and review use separate endpoints; a correction cannot preserve or acquire
`reviewed`, `ai_reviewed`, `approved`, or `rejected` in the same request. Public
serialization uses a correction only after a subsequent human-admin approval.
Submitting the same final status does not bypass role/type checks.

## Network and provider allowlists

Default LLM providers are local/offline:

```bash
export TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive", "ollama"]'
```

The incomplete OpenAI adapter has been removed from supported configuration.
Adding any future external provider is a separate privacy/data-transfer design
requiring an approved purpose, contract, retention assessment, full provider
contract, tests, and UI notice.

Ollama model names are not sufficient provenance because tags are mutable.
Configure an exact name-to-digest allowlist and verify it against `/api/tags`:

```bash
export TTLAB_OLLAMA_ALLOWED_MODEL_DIGESTS='{"qwen3:4b-instruct-2507-q4_K_M":"<64-hex-digest>"}'
```

An absent, mismatched, or unapproved digest fails closed or produces an explicit
offline fallback record; it is never silently treated as the requested model.
The provider verifies the installed tag digest immediately before and after a
generation call. Ollama's standard generation response may report only the tag,
not a digest. Such an answer may be returned after both checks, but its effective
model is the mutable tag, `generation_time_digest_verified` remains false, and a
warning explains that the checks are not an immutable generation-time
attestation. Only a response-reported matching digest permits the digest-bound
effective model identity. A different response tag/digest or a tag change
during the call fails to the explicitly recorded offline provider.

PDF download destinations default to the TTLAB hosts used by the curated
ingestion workflow:

```bash
export TTLAB_ALLOWED_PDF_HOSTS='["lab.tt", "temp.lab.tt"]'
```

An allowlist entry authorizes network contact, not trust in the file. Keep it
narrow. Downloader controls and residual risks are listed in `THREAT_MODEL.md`.
Automated acquisition/promotion is disabled in every service role because an
atomic multi-artifact generation switch is not implemented. Explicit
operator-run staging still carries DNS rebinding TOCTOU and hostile-parser risk;
egress isolation, parser sandboxing, CPU/memory/time limits, and malware
handling remain external controls.

## Input, browser, and response controls

- Default request-body cap: 1 MiB (`TTLAB_MAX_REQUEST_BYTES`).
- Public-generation limit: 20 requests/minute per process/client/path
  (`TTLAB_PUBLIC_GENERATION_REQUESTS_PER_MINUTE`).
- Public-generation work cap: at most two in-flight requests and four queued
  requests per API process by default
  (`TTLAB_PUBLIC_GENERATION_MAX_CONCURRENCY=2` and
  `TTLAB_PUBLIC_GENERATION_MAX_QUEUE=4`); a queued request waits at most two
  seconds by default (`TTLAB_PUBLIC_GENERATION_QUEUE_TIMEOUT_SECONDS=2.0`)
  before rejection.
- Default PDF cap: 25 MiB and 1,000 pages.
- Exact CORS origins; no credentialed CORS; explicit trusted hosts.
- `nosniff`, frame denial, no-referrer, restrictive permissions policy,
  API CSP, request IDs, no-store on admin/history responses, and production
  HSTS.
- Public artifact responses omit reviewer notes/identifiers and withhold draft
  corrections until the corrected artifact receives a subsequent human-admin
  approval. Chunk/artifact evidence for non-eligible papers is protected.

The in-process rate and generation concurrency/queue limiters are backstops, not
distributed abuse prevention or workload isolation. Production validation
therefore accepts only the declared single-API-worker topology. Any larger
deployment needs reverse-proxy/distributed request and concurrency controls plus
body, connection, queue, request-rate, execution-time, and response-time limits.

## Vulnerability and dependency procedure

Before a release:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.environment \
  --lock backend/requirements-lock.txt
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit --skip-editable --vulnerability-service osv --strict
npm --prefix frontend audit --audit-level=high
```

The environment validator checks the resolved installed environment against all
95 exact current lock pins; the audit then examines that resolved environment,
not the looser direct-input requirements file. Record tool versions, timestamps,
findings, accepted risks, and remediation in the release evidence. Do not
silently ignore advisories merely because a dependency is transitively
installed.

For a suspected incident: isolate the service, revoke affected tokens/provider
keys, preserve read-only copies of logs/database/manifests, determine affected
actors/items/request IDs, correct generated/public content through an
attributed review event, restore from a verified backup if required, notify the
institutional owner, and document the timeline and prevention change. Do not
delete an audit event to hide an error.
