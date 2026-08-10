# GCP and Vertex Gemini Deployment

## Runtime contract

The application has two independent controls:

- `TTLAB_RUNTIME_PROFILE=local` keeps SQLite, local files, SQLite FTS5, optional Ollama, and the offline-extractive path.
- `TTLAB_RUNTIME_PROFILE=gcp` requires Cloud SQL PostgreSQL, private Cloud Storage, production security settings, and a managed API provider policy. Public requests must use `provider=auto` and cannot select a model.

The first managed release uses Vertex Gemini only for Ask TTLAB composition and the conversational Idea Generator. Retrieval, the pinned local sentence-transformer, deterministic summaries, structured Finder, and podcast generation do not switch to Google models.

Vertex calls use `google-genai` with Vertex AI, API version `v1`, Application Default Credentials, the Cloud Run API service account, and location `global`. No API key, Google Search grounding, URL context, or model tools are used. The provider receives only the question/conversation and retrieved TTLAB passages. Ask failures fall back to the existing extractive answer with a machine-readable reason. Idea generation validates the configured Pydantic schema twice, retries invalid output once, and otherwise returns a provider-neutral error; it never invents a deterministic replacement.

The container installs `backend/requirements-gcp-lock.txt`, downloads the exact configured sentence-transformer revision during image build, records a deterministic snapshot checksum in `/opt/dense-model.sha256`, and forces Hugging Face/Transformers offline mode at runtime. Cloud Run never downloads model weights.

## Provision

Authenticate Terraform with an administrator identity, choose an immutable image digest, and create a variables file. The infrastructure operation is:

```bash
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp apply -var-file=production.tfvars
```

Required variables are `project_id`, `container_image`, `public_base_url`, and `public_hostname`. Set `cloud_build_service_account` when the project does not use the legacy project-number Cloud Build account. The configuration creates Artifact Registry, regional Cloud Run and Cloud SQL resources in `us-east1`, a private versioned bucket, API/job service accounts, least-privilege IAM, Secret Manager secrets and initial versions, Scheduler, and migration/maintenance Jobs. Only the API identity receives `roles/aiplatform.user`.

The Cloud SQL baseline is migration-controlled. The API never calls `create_all` or the SQLite additive migration in GCP mode and fails startup/readiness until `alembic_version` is at the configured head. Execute the migration job before first traffic:

```bash
gcloud run jobs execute ttlab-advisor-migrate --region us-east1 --wait
```

## Snapshot migration

Create the export from a stopped or otherwise stable source database. The exporter opens SQLite read-only and fails on a broken review chain or missing in-repository object:

```bash
PYTHONPATH=backend .venv/bin/python -m app.gcp_snapshot export \
  --database data/papers.db \
  --output /secure/path/advisor-snapshot-v1 \
  --project-root "$PWD"
```

The manifest records versioned JSONL table exports, row counts, SHA-256 checksums, object inventory, review-chain head, and every omission. Active admin sessions, pending/expired bulk previews, SQLite FTS tables, and Ollama model policy are deliberately omitted. Executed bulk history is retained without preview payloads; sync run history is retained while lease/manual-request fields are reset. Administrator password hashes and review history are retained.

Upload inventoried objects and import only into a newly migrated, empty database:

```bash
PYTHONPATH=backend .venv/bin/python -m app.gcp_snapshot upload-objects \
  --manifest /secure/path/advisor-snapshot-v1/manifest.json \
  --project-root "$PWD" \
  --gcs-prefix gs://BUCKET/corpus

PYTHONPATH=backend .venv/bin/python -m app.gcp_snapshot import \
  --snapshot /secure/path/advisor-snapshot-v1 \
  --gcs-prefix gs://BUCKET/corpus
```

The importer verifies export/object checksums, target emptiness, and the review-chain head inside one database transaction. Rebuild keyword metadata and publish vector generations only after the imported corpus identity matches the manifest.

Automatic live corpus/index promotion remains out of scope. After an authorized offline worker builds and validates a generation, publish it with `python -m app.gcp_indexes PATH_TO_INDEX`; the command uploads immutable generation files before advancing the GCS pointer. API instances TTL-check that pointer, verify both generation checksums and the database corpus identity through the existing index loader, then replace their in-memory cache.

## Release and rollback

`cloudbuild.yaml` builds the frontend and backend image, runs frontend tests and the backend suite in that immutable image, pushes it, executes migrations, deploys a tagged no-traffic revision, probes `/health` and `/ready`, and then promotes the latest revision. The equivalent operator entrypoint is:

```bash
scripts/release_gcp.sh PROJECT_ID us-east1 ttlab-advisor-api ttlab-advisor-migrate IMAGE_DIGEST
```

Do not promote unless restart/scale persistence, admin login, review-chain mutation, retrieval, Gemini Ask/citations, structured ideas, forced Vertex fallback, scheduled maintenance, redacted logs, backup/PITR evidence, quotas, and cost alerts have been checked in staging. Roll back application traffic to the prior Cloud Run revision. For incompatible data failures, restore Cloud SQL with PITR to a new instance and point a compatible revision at it; migrations must use expand/contract changes so the prior application revision remains readable.

The initial 2 vCPU, 4 GiB, concurrency 8, min 1, max 3, one-worker configuration is a starting point, not a scalability result. Recheck Gemini model lifecycle/availability before each release and preserve negative retrieval, QA, or load-test findings.
