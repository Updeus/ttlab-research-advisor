# Deployment Runbook

## Status and boundary

The repository contains a local/demo FastAPI/React system. No public production
deployment, uptime target, institutional identity integration, managed
monitoring, or TLS endpoint is claimed. The following is the minimum boundary
for a defensible deployment; institution-specific platform and privacy approval
remain external.

## Production configuration

Set secrets through the deployment secret manager, not a committed `.env`:

```bash
export TTLAB_SECURITY_MODE=production
export TTLAB_ALLOW_INSECURE_LOCAL_DEMO=false
export TTLAB_SERVICE_ROLE=api
export TTLAB_API_WORKER_COUNT=1
export TTLAB_SYNC_EXECUTION_MODE=disabled
export TTLAB_SYNC_ENABLED=false
export TTLAB_PUBLIC_GENERATION_MAX_CONCURRENCY=2
export TTLAB_PUBLIC_GENERATION_MAX_QUEUE=4
export TTLAB_PUBLIC_GENERATION_QUEUE_TIMEOUT_SECONDS=2.0
export TTLAB_PUBLIC_BASE_URL=https://advisor.example.edu
export TTLAB_FRONTEND_URL=https://advisor.example.edu
export TTLAB_TRUSTED_HOSTS='["advisor.example.edu"]'
export TTLAB_CORS_ORIGINS='["https://advisor.example.edu"]'
export TTLAB_AUTH_ACTORS_JSON='[{"token_sha256":"<digest>","actor_id":"<stable-id>","display_name":"<name>","role":"admin","reviewer_type":"human","active":true}]'
export TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive","ollama"]'
export TTLAB_OLLAMA_ALLOWED_MODEL_DIGESTS='{"<approved-model-name>":"<64-hex-digest>"}'
export TTLAB_ALLOWED_PDF_HOSTS='["lab.tt","temp.lab.tt"]'
export TTLAB_DATABASE_URL=sqlite:////srv/ttlab/private/papers.db
```

Production startup validates the mode, actor/admin presence, HTTPS URL, exact
CORS origins, trusted host, one-worker topology, and disabled ingestion/PDF
boundary. The service should run as an unprivileged user with read access only
to approved corpus files and write access only to its database/derived-data
directories.

Recommended API launch (behind a TLS proxy, without development reload):

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --workers 1 \
  --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
```

SQLite supports this bounded deployment best with one API worker. The public-
generation concurrency and bounded-wait queue controls above are process-local
backstops. Multi-worker or multi-host deployment requires deliberate database/
locking, distributed request/concurrency controls, workload timeouts, shared
index, and migration design rather than merely increasing the worker count.

Serve the compiled frontend as static files. Configure SPA fallback to
`index.html` only for frontend routes; never rewrite `/api/*`, `/health`, or
`/ready` failures into HTML.

## Offline corpus-maintenance boundary

The production API cannot acquire or parse PDFs. Automated synchronization is
also unavailable in an offline worker: both scheduled and manual paths stop
before discovery or mutation with
`atomic_generation_promotion_not_implemented`. This is intentional because the
repository has no atomic active-generation pointer spanning seed metadata,
SQLite rows, extracted files, chunks, vector indexes, and topic indexes.

To update a corpus, an operator must run discovery/import/extraction/indexing in
an isolated copy with restricted network access and no HTTP listener, bearer
tokens, or provider secrets. Validate the entire staged snapshot and checksum
inventory, quiesce API writes, create a recoverable backup, and replace the
active snapshot in a maintenance window. This deployment guide does not claim
that the final switch is automated, online-safe, or multi-process atomic. The
Admin surface reports the same disabled reason and cannot queue work.

## TLS proxy and network controls

- Terminate TLS 1.2+ at a maintained reverse proxy and redirect HTTP to HTTPS.
- Preserve the exact `Host`; accept forwarded headers only from the proxy IP.
- Enforce a request-body cap no larger than the application cap, connection and
  response timeouts, per-IP/actor rate limits, concurrent-request limits, and
  maximum header sizes.
- Allow inbound access only through the proxy. Bind Uvicorn to loopback/private
  service networking.
- Restrict staging-job egress to approved DNS/resolvers and PDF/model
  destinations. Block link-local, RFC1918, metadata-service, and control-plane
  ranges at the network layer as defense in depth.
- Run PDF acquisition/parsing separately under CPU/memory/time/filesystem limits,
  without bearer/provider secrets. The application reports that DNS rebinding
  TOCTOU and process isolation are not fully mitigated; enforce DNS pinning or an
  egress proxy plus sandbox/resource controls externally.

## Health, readiness, and monitoring

- `GET /health` is liveness only; it does not claim the corpus/index is usable.
- `GET /ready` requires SQLite plus complete, current keyword and
  feature-hashing authoritative indexes. The dense index is optional when
  absent, but a present partial/stale/corrupt dense index fails readiness. The
  response reports public-safe per-index status/counts and returns 503 without
  local paths or internal exception details when a required gate fails.
- Monitor liveness, readiness, 4xx/5xx rates, latency, disk/database size,
  backup age, index-manifest health, failed downloads/extractions, token failures,
  denied synchronization attempts and review/audit anomalies.

Application logs intentionally contain only method, route template, status,
duration, request ID, actor ID, and actor role. Disable Uvicorn raw access logs
or configure the proxy to omit query strings, authorization headers, cookies,
bodies, and provider prompts. Central log retention/access must match the
approved privacy schedule.

## Backup and restore

Corpus PDFs may have redistribution restrictions and are not automatically part
of a public backup/release. For private operational recovery:

1. Quiesce writes or use SQLite's online backup mechanism; do not copy a live
   database file blindly.
2. Back up the database, authoritative index plus manifest, approved metadata,
   generated/review state, and configuration schema separately from secrets.
3. Encrypt at rest/in transit, restrict access, and record timestamp, version,
   corpus snapshot/hash, checksums, and retention/expiry.
4. Restore into an isolated environment, run `PRAGMA quick_check`, foreign-key
   checks, index-manifest validation, and the smoke/test gates, then compare
   counts/checksums before promotion.
5. Exercise and record a restore periodically. An untested backup is not
   recovery evidence.

## Release and update checklist

```bash
PYTHONPATH=backend .venv/bin/python -m compileall -q backend/app
PYTHONPATH=backend .venv/bin/python -m pytest
(cd frontend && npm ci && npm run build && npm audit --omit=dev)
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.environment \
  --lock backend/requirements-lock.txt
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit --skip-editable --vulnerability-service osv --strict
```

The lock validator covers all 95 exact current pins, and `pip-audit` examines
the resolved installed environment. Auditing only `backend/requirements.txt`
would not establish either installed-state identity or lock conformance.

Then verify configuration with production environment variables, start in an
isolated staging environment, require anonymous 401 on admin/history/mutation
routes, exercise reviewer/admin transitions, check exact CORS/Host/TLS headers,
verify `/ready`, inspect redacted logs, and run backup/restore plus index/corpus
integrity gates. Scan the release for `.env`, tokens, API keys, database files,
restricted PDFs, absolute local paths, private history, and unlicensed content.

## Incident and correction

On suspected compromise or unsafe generated content: remove the service from
public traffic, revoke/rotate affected tokens and provider keys, preserve
read-only forensic copies and request IDs, identify affected items/actors,
notify the institutional owner, restore only from verified media, and publish
corrections through new attributed review events. Database owners can bypass
SQLite triggers; protect and reconcile centralized logs/backups for that threat.
