# Screenshot Evidence Checklist

Tracked interface images live under `thesis/figures/screenshots/`, but the
capture script never writes there. It stages new PNGs and
`capture-manifest.json` in a new direct child of an external, operator-created
`/tmp` or `/var/tmp` runtime. An AI-assisted audit may promote a governance or
aggregate evaluation capture after verifying that it contains no source text,
personal data, secrets, mutation, or unapproved record content and remains
print-readable. A source-bearing capture requires the applicable human rights/
publication decision before promotion; screenshot promotion is not blanket
human-required work.

`thesis/scripts/capture_interface_screenshots.mjs` accepts two capture sets:

- `TTLAB_SCREENSHOT_CAPTURE_SET=governance` stages the truthful empty-public-
  projection Finder state and a write-blocked aggregate Admin governance shell. It
  does not require, simulate, or execute remediation-v2 evidence.
- `TTLAB_SCREENSHOT_CAPTURE_SET=full` additionally stages only the identity-
  validated current remediation-v2 dashboard panel. It refuses a missing,
  partial, stale, or mismatched package and keeps historical v1 results outside
  that print-focused crop.

Both modes require distinct loopback frontend/API origins, a clean committed
worktree, a ready copied database plus exact copied authoritative indexes, and
an ephemeral least-privileged service reviewer. The actor can read protected
queues but cannot approve/reject, decide publication/rights, or trigger
ingestion. The browser route firewall blocks every POST/PATCH/PUT/DELETE; thus
the session is write-blocked even though an ordinary reviewer can save
corrections outside this capture workflow. The Finder form is never submitted.

Create the runtime before starting either server. This records the source hash
before application startup, creates an integrity-checked SQLite backup, and
copies indexes without symlinks. Run from a clean repository root:

```bash
repo_root="$(pwd)"
capture_root="$(mktemp -d /tmp/ttlab-screenshot-capture.XXXXXX)"
source_db_sha256="$(sha256sum data/papers.db | cut -d ' ' -f 1)"
PYTHONPATH=backend .venv/bin/python -m app.reproducibility.database_snapshot \
  --source data/papers.db \
  --target "$capture_root/papers.db" \
  --evidence "$capture_root/database-snapshot.json"
cp -a data/indexes "$capture_root/indexes"
```

Start the backend from `capture_root` so all relative index paths resolve to the
copy. Generate a one-run token of at least 32 characters and configure only its
SHA-256 in `TTLAB_AUTH_ACTORS_JSON`; use actor ID `capture-service`, role
`reviewer`, reviewer type `service`, and `active: true`. Also set the copied
database/lock paths, `TTLAB_SECURITY_MODE=local_demo`,
`TTLAB_ALLOW_INSECURE_LOCAL_DEMO=false`, `TTLAB_SERVICE_ROLE=api`,
`TTLAB_SYNC_ENABLED=false`, `TTLAB_SYNC_EXECUTION_MODE=disabled`, the exact
frontend CORS origin, and `PYTHONPATH=<repository>/backend`. Start the frontend
from the repository with `npm --prefix frontend run dev:e2e`.

Then stage governance captures with the same one-run token:

```bash
TTLAB_CAPTURE_ISOLATED=1 \
TTLAB_SCREENSHOT_CAPTURE_SET=governance \
TTLAB_SCREENSHOT_URL=http://127.0.0.1:4173 \
TTLAB_API_URL=http://127.0.0.1:8000 \
TTLAB_SCREENSHOT_REVIEWER_TOKEN="$capture_token" \
TTLAB_SCREENSHOT_EXPECTED_ACTOR_ID=capture-service \
TTLAB_SCREENSHOT_RUNTIME_ROOT="$capture_root" \
TTLAB_SCREENSHOT_SOURCE_DB_PATH="$repo_root/data/papers.db" \
TTLAB_SCREENSHOT_SOURCE_DB_SHA256="$source_db_sha256" \
TTLAB_SCREENSHOT_RUNTIME_DB_PATH="$capture_root/papers.db" \
TTLAB_SCREENSHOT_DATABASE_SNAPSHOT_EVIDENCE="$capture_root/database-snapshot.json" \
TTLAB_SCREENSHOT_RUNTIME_INDEX_DIR="$capture_root/indexes" \
TTLAB_SCREENSHOT_OUTPUT_DIR="$capture_root/staged" \
node thesis/scripts/capture_interface_screenshots.mjs
```

The script rejects an existing output path, symlinked runtime assets, a hard-
linked database, snapshot/source-hash disagreement, a non-exact index copy, or
new source-database WAL/journal sidecars. It records hashes and safe labels, not
runtime paths or the token. Its application-state comparison is accurately an
observed aggregate summary; source DB/index hashes are the filesystem mutation
guard.

Do not use `full` before the prospective v2 `prepare`/one-`evaluate`-invocation-
per-fresh-workspace/validation sequence has produced the canonical attested
package. The first accepted source candidate is confirmatory; later full runs
are unchanged-protocol deterministic replications, not opportunities to tune or
change cases. Use
`governance` when checking layout before that run; screenshots are never a
reason to execute held-out evaluation early.

When reviewing any staged image, verify:

- `capture-manifest.json` has `status: pass`, `promotable: true`, the requested
  capture set, the exact expected PNG inventory, and matching hashes;
- errors, blocked requests, request failures, console errors, and page errors
  are empty, the aggregate state summary is unchanged, and source assets are
  recorded unchanged;
- the public Finder is visibly empty pending human editorial/rights approval
  and does not expose the technical corpus;
- the Admin crop says protected/write-blocked, identifies the service reviewer, and
  contains aggregate state only—not item text, reviewer notes, tokens, or
  contact data;
- an evaluation crop says AI-silver, technical scope only, no human validation,
  no entailment claim, and public projection not exercised;
- feature hashing is named `feature_hashing`, never `semantic` or learned dense;
- generated suggestions remain distinct from source facts and paper-stated
  future work; and
- text remains readable at intended thesis print width.

Older tracked route screenshots are historical/manual captures unless their
own committed provenance says otherwise. They must not be described as current
automated evidence. All screenshot files are excluded from the sanitized
reproducibility archive because raster content can contain paper passages,
answers, or identifiers that cannot be field-redacted reliably. TTLAB project/
corpus authorization is not blanket permission to redistribute such source
content.
