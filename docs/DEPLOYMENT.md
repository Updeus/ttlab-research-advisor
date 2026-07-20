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
export TTLAB_PUBLIC_BASE_URL=https://advisor.example.edu
export TTLAB_FRONTEND_URL=https://advisor.example.edu
export TTLAB_TRUSTED_HOSTS='["advisor.example.edu"]'
export TTLAB_CORS_ORIGINS='["https://advisor.example.edu"]'
export TTLAB_AUTH_ACTORS_JSON='[{"token_sha256":"<digest>","actor_id":"<stable-id>","display_name":"<name>","role":"admin","reviewer_type":"human","active":true}]'
export TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive","ollama"]'
export TTLAB_ALLOWED_PDF_HOSTS='["lab.tt","temp.lab.tt"]'
export TTLAB_DATABASE_URL=sqlite:////srv/ttlab/private/papers.db
export TTLAB_SYNC_ENABLED=true
export TTLAB_SYNC_CRON='0 2 * * *'
export TTLAB_SYNC_TIMEZONE=America/La_Paz
export TTLAB_SYNC_MAX_PAGES=3
export TTLAB_SYNC_DOWNLOAD_PDFS=true
export TTLAB_SYNC_DENSE_INDEX_POLICY=if_present
```

Production startup validates the mode, actor/admin presence, HTTPS URL, exact
CORS origins, and trusted host. The service should run as an unprivileged user
with read access only to approved corpus files and write access only to its
database/derived-data directories.

Recommended API launch (behind a TLS proxy, without development reload):

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --workers 1 \
  --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
```

SQLite supports this bounded deployment best with one API worker. Multi-worker
or multi-host deployment requires deliberate database/locking, distributed rate
limit, shared index, and migration design rather than merely increasing the
worker count.

Serve the compiled frontend as static files. Configure SPA fallback to
`index.html` only for frontend routes; never rewrite `/api/*`, `/health`, or
`/ready` failures into HTML.

## Scheduled ingestion worker

Deploy one project-owned ingestion worker as a separate service. Do not start a
scheduler in every API process. The worker uses the same database and derived-
data directories as the API, while a persisted lease prevents a scheduled and
manual run from overlapping. It imports only new or changed catalogue records;
an empty or failed scrape records a failed run and preserves the current
corpus.

Example `/etc/systemd/system/ttlab-ingestion.service`:

```ini
[Unit]
Description=TTLAB publication synchronization worker
After=network-online.target ttlab-api.service
Wants=network-online.target

[Service]
Type=simple
User=ttlab
Group=ttlab
WorkingDirectory=/srv/ttlab/app
EnvironmentFile=/etc/ttlab/advisor.env
Environment=PYTHONPATH=/srv/ttlab/app/backend
ExecStart=/srv/ttlab/app/.venv/bin/python -m app.ingestion.sync_worker
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/srv/ttlab/private /srv/ttlab/app/data

[Install]
WantedBy=multi-user.target
```

After installing or changing the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ttlab-ingestion.service
sudo systemctl status ttlab-ingestion.service
sudo journalctl -u ttlab-ingestion.service -n 100 --no-pager
```

The schedule accepts a fixed daily minute/hour expression only. The worker also
polls for protected manual requests created from the Admin overview, even when
`TTLAB_SYNC_ENABLED=false`. `TTLAB_SYNC_DENSE_INDEX_POLICY=if_present` avoids
unexpected model acquisition: it refreshes dense retrieval only if an
authoritative dense index already exists. Model download remains an explicit
operator action.

## TLS proxy and network controls

- Terminate TLS 1.2+ at a maintained reverse proxy and redirect HTTP to HTTPS.
- Preserve the exact `Host`; accept forwarded headers only from the proxy IP.
- Enforce a request-body cap no larger than the application cap, connection and
  response timeouts, per-IP/actor rate limits, concurrent-request limits, and
  maximum header sizes.
- Allow inbound access only through the proxy. Bind Uvicorn to loopback/private
  service networking.
- Restrict ingestion-worker egress to approved DNS/resolvers and PDF/model
  destinations. Block link-local, RFC1918, metadata-service, and control-plane
  ranges at the network layer as defense in depth.
- Run PDF acquisition/parsing separately under CPU/memory/time/filesystem limits,
  without bearer/provider secrets, for higher assurance.

## Health, readiness, and monitoring

- `GET /health` is liveness only; it does not claim the corpus/index is usable.
- `GET /ready` requires SQLite plus complete, current keyword and
  feature-hashing authoritative indexes. The dense index is optional when
  absent, but a present partial/stale/corrupt dense index fails readiness. The
  response reports public-safe per-index status/counts and returns 503 without
  local paths or internal exception details when a required gate fails.
- Monitor liveness, readiness, 4xx/5xx rates, latency, disk/database size,
  backup age, index-manifest health, failed downloads/extractions, token failures,
  ingestion-worker liveness, missed/failed synchronization runs, pending manual
  requests, and review/audit anomalies.

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
.venv/bin/python -m pip_audit -r backend/requirements.txt
```

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
