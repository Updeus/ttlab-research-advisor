# Security Guide

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
Its actor is typed `service`, so it cannot create `reviewed`, `ai_reviewed`,
`approved`, or `rejected` decisions; configure the corresponding authenticated
human/AI actor when exercising real review-state transitions.

`TTLAB_SECURITY_MODE=production` fails startup unless:

- at least one active admin actor is configured;
- `TTLAB_PUBLIC_BASE_URL` uses HTTPS;
- the public hostname is in `TTLAB_TRUSTED_HOSTS`;
- all CORS origins use HTTPS; and
- insecure local-demo bypass is disabled.

Interactive OpenAPI/ReDoc endpoints are disabled in production.

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

- Public: publication metadata, bounded eligible-source snippets, search,
  aggregate diagnostics/evaluation, transient Ask, and transient Extension
  Finder.
- Reviewer/admin: histories/items containing submitted questions/profiles,
  admin overview/queues/events, full extracted chunks, one-paper persisted
  artifact generation, and review/correction mutations.
- Human admin only: administrative approval/rejection. Batch artifact generation
  requires the `admin` role (including an explicitly labeled demo service actor).
- AI reviewer: must record `ai_reviewed`; it cannot represent human review or
  administrative approval.

Every review event records the stable actor, reviewer type/role, server request
ID, change diff, timestamp, previous event hash, and its own hash. SQLite blocks
event updates/deletes. This is application/database-process immutability, not a
claim that a machine/database owner cannot rewrite the SQLite file.

Any metadata, generated-artifact, or recommendation correction is a new
reviewable version and is therefore forced back to `needs_review`. A correction
cannot preserve or acquire `reviewed`, `ai_reviewed`, `approved`, or `rejected`
status in the same request; a subsequent attributed review decision is required.
Submitting the same final status does not bypass role/type checks.

## Network and provider allowlists

Default LLM providers are local/offline:

```bash
export TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive", "ollama"]'
```

Adding `openai` is a separate privacy/data-transfer decision. The current
adapter is non-required; do not enable an external provider without an approved
purpose, contract, retention assessment, and UI notice.

PDF download destinations default to the TTLAB hosts used by the curated
ingestion workflow:

```bash
export TTLAB_ALLOWED_PDF_HOSTS='["lab.tt", "temp.lab.tt"]'
```

An allowlist entry authorizes network contact, not trust in the file. Keep it
narrow. Downloader controls and residual risks are listed in `THREAT_MODEL.md`.

## Input, browser, and response controls

- Default request-body cap: 1 MiB (`TTLAB_MAX_REQUEST_BYTES`).
- Public-generation limit: 20 requests/minute per process/client/path
  (`TTLAB_PUBLIC_GENERATION_REQUESTS_PER_MINUTE`).
- Default PDF cap: 25 MiB and 1,000 pages.
- Exact CORS origins; no credentialed CORS; explicit trusted hosts.
- `nosniff`, frame denial, no-referrer, restrictive permissions policy,
  API CSP, request IDs, no-store on admin/history responses, and production
  HSTS.
- Public artifact responses omit reviewer notes/identifiers and withhold draft
  corrections until the corrected artifact receives a subsequent human-admin
  approval. Chunk/artifact evidence for non-eligible papers is protected.

The in-process rate limiter is a backstop, not distributed abuse prevention.
The reverse proxy must enforce body, connection, request-rate, and timeout
limits for every worker.

## Vulnerability and dependency procedure

Before a release:

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
.venv/bin/python -m pip install pip-audit
.venv/bin/python -m pip_audit -r backend/requirements.txt
(cd frontend && npm audit --omit=dev)
```

Record tool versions, timestamps, findings, accepted risks, and remediation in
the release evidence. Do not silently ignore advisories merely because a
dependency is transitively installed.

For a suspected incident: isolate the service, revoke affected tokens/provider
keys, preserve read-only copies of logs/database/manifests, determine affected
actors/items/request IDs, correct generated/public content through an
attributed review event, restore from a verified backup if required, notify the
institutional owner, and document the timeline and prevention change. Do not
delete an audit event to hide an error.
