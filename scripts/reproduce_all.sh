#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="full"
WORK=""
INSTALL=0
KEEP_WORK=1
RELEASE_VERSION="0.1.0-remediation"
RETAIN_DIR=""
SOURCE_DB="$ROOT/data/papers.db"
PYTHON="$ROOT/.venv/bin/python"
RUN_ROOT=""
WORK_SENTINEL_NAME=".ttlab-reproduction-workspace"
WORK_SENTINEL_TOKEN=""
WORK_DEVICE_INODE=""

usage() {
  cat <<'EOF'
Reproduce the TTLAB research artefacts and final verification gates.

Usage: scripts/reproduce_all.sh [options]

Options:
  --mode quick|full     quick validates distributable evidence; full rebuilds the authorized corpus (default: full)
  --work-dir PATH       isolated output directory (default: tmp/reproduce/<mode>)
  --source-db PATH      authorized local source DB for full mode (default: data/papers.db)
  --install             install pinned Python and npm dependencies before verification
  --release-version V   sanitized release version (default: 0.1.0-remediation)
  --retain-dir PATH     retain verified content-free attestations outside the isolated workspace
  --discard-work        remove the isolated workspace after a successful run
  -h, --help            show this help

Full mode requires separately authorized local PDFs referenced by the source DB
and the pinned dense model in the local Hugging Face cache. It never downloads
or republishes PDFs. Quick mode cannot reproduce corpus-dependent metrics and
must not be cited as a full experimental reproduction.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '\n[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

while (($#)); do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --work-dir) WORK="${2:-}"; shift 2 ;;
    --source-db) SOURCE_DB="${2:-}"; shift 2 ;;
    --install) INSTALL=1; shift ;;
    --release-version) RELEASE_VERSION="${2:-}"; shift 2 ;;
    --retain-dir) RETAIN_DIR="${2:-}"; shift 2 ;;
    --discard-work) KEEP_WORK=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$MODE" == "quick" || "$MODE" == "full" ]] || die "--mode must be quick or full"
[[ -n "$WORK" ]] || WORK="$ROOT/tmp/reproduce/$MODE"
if [[ -n "$RETAIN_DIR" && "$RETAIN_DIR" != /* ]]; then
  RETAIN_DIR="$ROOT/$RETAIN_DIR"
fi
WORK="$(realpath -m -- "$WORK")"
case "$WORK" in
  /|/tmp|/var|/var/tmp|/home|/root|/mnt|/mnt/c|/mnt/c/Users)
    die "--work-dir must be a new, narrowly scoped directory, not a broad or sensitive root: $WORK"
    ;;
esac
[[ "$WORK" != "$ROOT" && "$ROOT" != "$WORK"/* ]] || \
  die "--work-dir cannot be the repository root or one of its ancestors: $WORK"
if [[ "$WORK" == "$ROOT"/* && "$WORK" != "$ROOT/tmp/reproduce/"* ]]; then
  die "repository-local --work-dir must be below $ROOT/tmp/reproduce"
fi
if [[ "$WORK" != "$ROOT/tmp/reproduce/"* && "$WORK" != /tmp/* && "$WORK" != /var/tmp/* ]]; then
  die "external --work-dir must be a unique child of /tmp or /var/tmp"
fi
[[ ! -e "$WORK" ]] || die "--work-dir must be new and absent: $WORK"
if [[ -n "$RETAIN_DIR" ]]; then
  RETAIN_DIR="$(realpath -m -- "$RETAIN_DIR")"
  [[ "$RETAIN_DIR" != "$WORK" && "$RETAIN_DIR" != "$WORK"/* ]] || \
    die "--retain-dir must remain outside the disposable reproduction workspace"
fi
mkdir -p "$(dirname "$WORK")"
mkdir "$WORK"
WORK_SENTINEL_TOKEN="ttlab-reproduction:${BASHPID}:$(date -u '+%Y%m%dT%H%M%SZ')"
printf '%s\n' "$WORK_SENTINEL_TOKEN" > "$WORK/$WORK_SENTINEL_NAME"
WORK_DEVICE_INODE="$(stat -Lc '%d:%i' "$WORK")"
mkdir "$WORK/logs" "$WORK/artifacts" "$WORK/runtime-tmp"
export TMPDIR="$WORK/runtime-tmp"
export TEMP="$WORK/runtime-tmp"
export TMP="$WORK/runtime-tmp"
SOURCE_DB="$(realpath -m "$SOURCE_DB")"
[[ "$SOURCE_DB" != "$WORK" && "$SOURCE_DB" != "$WORK"/* ]] || \
  die "--source-db must remain outside the disposable reproduction workspace"
RUN_ROOT="$WORK/source"
[[ ! -e "$RUN_ROOT" ]] || die "reproduction source snapshot already exists: $RUN_ROOT"

verify_workspace_ownership() {
  [[ -d "$WORK" && ! -L "$WORK" ]] || die "reproduction workspace is missing or became a symlink"
  [[ "$(stat -Lc '%d:%i' "$WORK")" == "$WORK_DEVICE_INODE" ]] || \
    die "reproduction workspace identity changed; refusing cleanup"
  [[ -f "$WORK/$WORK_SENTINEL_NAME" && ! -L "$WORK/$WORK_SENTINEL_NAME" ]] || \
    die "reproduction workspace ownership sentinel is missing"
  [[ "$(<"$WORK/$WORK_SENTINEL_NAME")" == "$WORK_SENTINEL_TOKEN" ]] || \
    die "reproduction workspace ownership sentinel changed"
  [[ "$RUN_ROOT" == "$WORK/source" ]] || die "run-root containment changed"
}

command -v git >/dev/null || die "git is required"
command -v python3 >/dev/null || die "python3 is required"
command -v npm >/dev/null || die "npm is required"
command -v node >/dev/null || die "node is required"
command -v qpdf >/dev/null || die "qpdf is required for PDF preflight"
command -v pdfinfo >/dev/null || die "pdfinfo is required for PDF preflight"
command -v pdffonts >/dev/null || die "pdffonts is required for PDF preflight"
command -v pdftotext >/dev/null || die "pdftotext is required for PDF preflight"
command -v pdftoppm >/dev/null || die "pdftoppm is required for page rendering"
command -v rg >/dev/null || die "ripgrep (rg) is required for fail-loud manuscript text checks"
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_TREE="$(git -C "$ROOT" rev-parse "${SOURCE_COMMIT}^{tree}")"
git -C "$ROOT" worktree add --detach "$RUN_ROOT" "$SOURCE_COMMIT" >/dev/null
[[ -z "$(git -C "$RUN_ROOT" status --porcelain --untracked-files=all)" ]] || die "detached source worktree is not clean at creation"
export PYTHONPATH="$RUN_ROOT/backend"
if ((INSTALL)); then
  python3 -m venv "$WORK/.venv"
  PYTHON="$WORK/.venv/bin/python"
else
  [[ -x "$PYTHON" ]] || die "missing .venv/bin/python; create the pinned environment or rerun with --install"
  [[ -d "$ROOT/frontend/node_modules" ]] || die "frontend/node_modules is absent; rerun with --install"
  ln -s "$ROOT/frontend/node_modules" "$RUN_ROOT/frontend/node_modules"
fi

run_logged() {
  local label="$1"; shift
  log "$label"
  {
    printf 'command:'
    printf ' %q' "$@"
    printf '\n'
    "$@"
  } 2>&1 | tee "$WORK/logs/${label}.log"
}

run_in_source() {
  local label="$1"; shift
  log "$label"
  {
    printf 'cwd: %s\ncommand:' "$RUN_ROOT"
    printf ' %q' "$@"
    printf '\n'
    (cd "$RUN_ROOT" && "$@")
  } 2>&1 | tee "$WORK/logs/${label}.log"
}

if ((INSTALL)); then
  run_logged install-python "$PYTHON" -m pip install -r "$RUN_ROOT/backend/requirements-lock.txt"
  run_logged install-frontend npm --prefix "$RUN_ROOT/frontend" ci
  run_logged install-browser "$RUN_ROOT/frontend/node_modules/.bin/playwright" install chromium
fi

run_logged dependency-imports "$PYTHON" -c \
  'import fastapi,httpx,jsonschema,fitz,sqlmodel; import sentence_transformers,torch,pytesseract; print("python-dependencies=ready")'
run_in_source python-lock-validation "$PYTHON" -m app.reproducibility.environment \
  --lock "$RUN_ROOT/backend/requirements-lock.txt" \
  --out "$WORK/artifacts/environment/python_environment.json"
run_logged python-dependency-check "$PYTHON" -m pip check
run_logged python-security-audit "$PYTHON" -m pip_audit --skip-editable \
  --vulnerability-service osv --strict
run_logged frontend-security-audit npm --prefix "$RUN_ROOT/frontend" audit --audit-level=high

[[ -z "$(git -C "$RUN_ROOT" status --porcelain --untracked-files=all)" ]] || die "source worktree changed before clean release construction"
run_in_source release-build "$PYTHON" -m app.reproducibility.release build \
  --version "$RELEASE_VERSION" --out-dir "$WORK/artifacts/release_bundle" \
  --evidence-dir "$WORK/artifacts/release"
RELEASE_ARCHIVE="$WORK/artifacts/release_bundle/ttlab-research-advisor-${RELEASE_VERSION}-${SOURCE_COMMIT:0:12}.tar.gz"
run_in_source release-verify "$PYTHON" -m app.reproducibility.release verify "$RELEASE_ARCHIVE"

run_in_source external-sanity "$PYTHON" -m app.evaluation.external_sanity \
  --out-dir "$WORK/artifacts/external_sanity"
run_in_source documentation-validation "$PYTHON" scripts/validate_documentation.py

run_in_source backend-tests "$PYTHON" -m pytest
run_logged frontend-unit npm --prefix "$RUN_ROOT/frontend" test
run_logged frontend-build npm --prefix "$RUN_ROOT/frontend" run build
run_logged frontend-e2e npm --prefix "$RUN_ROOT/frontend" run test:e2e

if [[ "$MODE" == "full" ]]; then
  [[ -s "$SOURCE_DB" ]] || die "full mode requires an authorized source database: $SOURCE_DB"
  PDF_COUNT="$(find "$ROOT/data/pdfs" -maxdepth 1 -type f -name '*.pdf' | wc -l)"
  ((PDF_COUNT > 0)) || die "full mode requires separately authorized local PDFs under data/pdfs"
  run_in_source database-snapshot "$PYTHON" -m app.reproducibility.database_snapshot \
    --source "$SOURCE_DB" --target "$RUN_ROOT/data/papers.db" \
    --evidence "$WORK/artifacts/database_snapshot.json"
  cp -a "$ROOT/data/pdfs/." "$RUN_ROOT/data/pdfs/"
  export TTLAB_DATABASE_URL="sqlite:///$RUN_ROOT/data/papers.db"

  run_in_source seed-import "$PYTHON" -m app.ingestion.manual_import --seed "$RUN_ROOT/data/seed/papers.json"
  run_in_source metadata-repair "$PYTHON" -m app.ingestion.metadata_cleaner repair-authors
  run_in_source extraction env \
    TTLAB_SERVICE_ROLE=offline_worker \
    TTLAB_SYNC_EXECUTION_MODE=offline_single_writer \
    "$PYTHON" -m app.ingestion.pdf_parser extract --overwrite --out-dir "$RUN_ROOT/data/extracted_text"
  run_in_source pdf-identity-audit "$PYTHON" -m app.ingestion.metadata_cleaner audit-pdf-titles
  run_in_source chunking "$PYTHON" -m app.indexing.chunker chunk --overwrite --out-dir "$RUN_ROOT/data/chunks"
  run_in_source generation-reconciliation "$PYTHON" -m app.ingestion.generation_reconciler reconcile \
    --extraction-dir "$RUN_ROOT/data/extracted_text" \
    --chunks-dir "$RUN_ROOT/data/chunks" \
    --pdf-dir "$RUN_ROOT/data/pdfs"
  run_in_source keyword-index "$PYTHON" -m app.indexing.keyword_search rebuild
  run_in_source hashing-index "$PYTHON" -m app.indexing.embedder index \
    --provider feature_hashing --out "$RUN_ROOT/data/indexes/feature_hashing_embeddings.json"
  run_in_source dense-index "$PYTHON" -m app.indexing.embedder index \
    --provider dense --out "$RUN_ROOT/data/indexes/dense_embeddings.json" --device cpu
  run_in_source hashing-index-validation "$PYTHON" -m app.indexing.embedder validate \
    --provider feature_hashing --index "$RUN_ROOT/data/indexes/feature_hashing_embeddings.json"
  run_in_source dense-index-validation "$PYTHON" -m app.indexing.embedder validate \
    --provider dense --index "$RUN_ROOT/data/indexes/dense_embeddings.json"

  [[ -z "$(git -C "$RUN_ROOT" status --porcelain --untracked-files=all)" ]] || die "source worktree changed before full performance benchmark"
  run_in_source performance-full "$PYTHON" -m app.evaluation.performance_benchmark \
    --profile full --repetitions 3 --database "$RUN_ROOT/data/papers.db" --runtime-root "$RUN_ROOT" \
    --out "$WORK/artifacts/performance/performance_full_results.json"
  run_in_source performance-full-validation "$PYTHON" -m app.evaluation.performance_validator \
    "$WORK/artifacts/performance/performance_full_results.json" \
    --expected-profile full --expected-repetitions 3 \
    --out "$WORK/artifacts/performance/performance_validation.json"
  mkdir -p "$RUN_ROOT/artifacts/phase6/performance"
  install -m 0644 "$WORK/artifacts/performance/performance_full_results.json" \
    "$RUN_ROOT/artifacts/phase6/performance/performance_full_results.json"
  install -m 0644 "$WORK/artifacts/performance/performance_validation.json" \
    "$RUN_ROOT/artifacts/phase6/performance/performance_validation.json"

  run_in_source phase1-evidence "$PYTHON" scripts/capture_phase1_evidence.py \
    --database "$RUN_ROOT/data/papers.db" --out "$RUN_ROOT/artifacts/phase1/phase1_evidence.json"
  run_in_source section-silver-validator "$PYTHON" data/evaluation/validate_section_quality_silver_v1.py \
    --database "$RUN_ROOT/data/papers.db" --evaluate-current

  run_in_source retrieval-label-validator "$PYTHON" data/evaluation/validate_retrieval_silver_v1.py
  run_in_source retrieval-experiment "$PYTHON" -m app.evaluation.retrieval_experiment \
    --questions "$RUN_ROOT/data/evaluation/retrieval_silver_v1.jsonl" \
    --schema "$RUN_ROOT/data/evaluation/retrieval_eval_results.schema.json" \
    --output "$RUN_ROOT/artifacts/phase2/retrieval" --bootstrap-repetitions 10000

  run_in_source qa-build-cases "$PYTHON" "$RUN_ROOT/data/evaluation/run_qa_faithfulness_v1.py" build-cases
  run_in_source qa-feature-hashing-answers "$PYTHON" "$RUN_ROOT/data/evaluation/run_qa_faithfulness_v1.py" \
    run-answers --mode feature_hashing --provider offline_extractive --top-k 5 \
    --output-stem offline_extractive_feature_hashing
  run_in_source qa-hybrid-answers "$PYTHON" "$RUN_ROOT/data/evaluation/run_qa_faithfulness_v1.py" \
    run-answers --mode hybrid --provider offline_extractive --top-k 5 \
    --output-stem offline_extractive_hybrid_heuristic
  run_in_source qa-ollama-availability "$PYTHON" "$RUN_ROOT/data/evaluation/run_qa_faithfulness_v1.py" check-ollama
  run_in_source qa-ai-review "$PYTHON" "$RUN_ROOT/data/evaluation/review_qa_faithfulness_v1.py"
  run_in_source qa-faithfulness-validator "$PYTHON" "$RUN_ROOT/data/evaluation/validate_qa_faithfulness_v1.py"

  run_in_source recommendation-proxy "$PYTHON" -m app.evaluation.recommendation_proxy_eval \
    --profiles "$RUN_ROOT/data/evaluation/recommendation_profiles_v1.jsonl" \
    --schema "$RUN_ROOT/data/evaluation/recommendation_profiles_v1.schema.json" \
    --prompt "$RUN_ROOT/data/evaluation/recommendation_proxy_review_prompt_v1.md" \
    --dense-manifest "$RUN_ROOT/data/indexes/dense_embeddings.manifest.json" \
    --out-dir "$RUN_ROOT/artifacts/phase4/recommendation_proxy_v1"
  run_in_source recommendation-evidence-validator "$PYTHON" "$RUN_ROOT/data/evaluation/validate_recommendation_proxy_v1.py" \
    --artifact-dir "$RUN_ROOT/artifacts/phase4/recommendation_proxy_v1"
  run_in_source topic-author-silver-validator "$PYTHON" "$RUN_ROOT/data/evaluation/validate_topic_author_silver_v1.py"
  run_in_source topic-author-evaluation "$PYTHON" -m app.evaluation.topic_author_eval \
    --output-dir "$RUN_ROOT/artifacts/phase4/topic_author"
  run_in_source generated-output-review "$PYTHON" -m app.evaluation.generated_output_review \
    --database "$RUN_ROOT/data/papers.db" \
    --output-dir "$RUN_ROOT/artifacts/phase4/generated_output_review" --apply-live

  # Prospective remediation-v2 runs only after every historical v1 gate.  The
  # suite freezes the rebuilt run-local database and complete backend/evaluation
  # source inventory,
  # evaluates the already-fixed selective-response threshold without tuning,
  # and regenerates the one canonical committed package path consumed by the
  # dashboard and release builder. The tracked source database remains
  # untouched because the runner uses a temporary SQLite copy. A committed
  # prior package is retained outside the source tree for deterministic metric
  # comparison instead of being destroyed.
  export TTLAB_V2_ARTIFACT_DIR="$RUN_ROOT/artifacts/peer_review_remediation/v2"
  export TTLAB_V2_RESTRICTED_DIR="$WORK/restricted/peer_review_remediation/v2"
  V2_PRIOR_PACKAGE="$WORK/prior-canonical-peer-review-remediation-v2"
  [[ "$TTLAB_V2_ARTIFACT_DIR" == "$RUN_ROOT/artifacts/peer_review_remediation/v2" ]] || die "v2 versionable output must use the canonical package path"
  [[ "$TTLAB_V2_RESTRICTED_DIR" != "$RUN_ROOT"/* ]] || die "restricted v2 raw output directory must remain outside the source/release tree"
  if [[ -e "$TTLAB_V2_ARTIFACT_DIR" ]]; then
    [[ ! -e "$V2_PRIOR_PACKAGE" ]] || die "prior canonical v2 package backup already exists: $V2_PRIOR_PACKAGE"
    mv "$TTLAB_V2_ARTIFACT_DIR" "$V2_PRIOR_PACKAGE"
  fi
  run_in_source remediation-v2-prepare "$PYTHON" \
    "$RUN_ROOT/data/evaluation/run_peer_review_remediation_v2.py" prepare
  run_in_source remediation-v2-evaluate "$PYTHON" \
    "$RUN_ROOT/data/evaluation/run_peer_review_remediation_v2.py" evaluate
  run_in_source remediation-v2-validate "$PYTHON" \
    "$RUN_ROOT/data/evaluation/validate_peer_review_remediation_v2.py"
  for restricted_name in qa_full_raw_v2.jsonl finder_full_raw_v2.jsonl topic_full_raw_v2.jsonl; do
    [[ -s "$TTLAB_V2_RESTRICTED_DIR/$restricted_name" ]] || die "missing rights-sensitive local v2 raw output: $restricted_name"
  done
  [[ -z "$(find "$TTLAB_V2_ARTIFACT_DIR" -type f -name '*full_raw*' -print -quit)" ]] || \
    die "rights-sensitive v2 raw output leaked into the canonical versionable package"
  if [[ -d "$V2_PRIOR_PACKAGE" ]]; then
    for deterministic_name in \
      qa_raw_outputs_v2.jsonl qa_review_pass1_v2.jsonl qa_review_pass2_v2.jsonl \
      qa_disagreements_v2.json qa_metrics_v2.json \
      finder_raw_outputs_v2.jsonl finder_review_pass1_v2.jsonl finder_review_pass2_v2.jsonl \
      finder_disagreements_v2.json finder_metrics_v2.json \
      topic_predictions_v2.jsonl topic_metrics_v2.json \
      ocr_fixture_results_v2.json manuscript_macros_v2.tex; do
      [[ -f "$V2_PRIOR_PACKAGE/$deterministic_name" ]] || die "prior canonical v2 package lacks deterministic reference: $deterministic_name"
      prior_normalized_hash="$("$PYTHON" "$RUN_ROOT/data/evaluation/run_peer_review_remediation_v2.py" normalized-hash "$V2_PRIOR_PACKAGE/$deterministic_name")"
      reproduced_normalized_hash="$("$PYTHON" "$RUN_ROOT/data/evaluation/run_peer_review_remediation_v2.py" normalized-hash "$TTLAB_V2_ARTIFACT_DIR/$deterministic_name")"
      [[ "$prior_normalized_hash" == "$reproduced_normalized_hash" ]] || \
        die "reproduced v2 structural artifact differs after timestamp normalization: $deterministic_name"
    done
  fi

else
  export TTLAB_DATABASE_URL="sqlite:///$RUN_ROOT/data/papers.db"
  run_in_source quick-seed-import "$PYTHON" -m app.ingestion.manual_import --seed "$RUN_ROOT/data/seed/papers.json"
  run_logged qa-public-manifest "$PYTHON" -c \
    "import json,pathlib; p=pathlib.Path('$RUN_ROOT/artifacts/phase3/qa/qa_faithfulness_manifest_v1.json'); assert json.loads(p.read_text())['status']=='executed_and_validated'; print('qa-public-manifest=valid')"
  [[ -z "$(git -C "$RUN_ROOT" status --porcelain --untracked-files=all)" ]] || die "source worktree changed before quick performance benchmark"
  run_in_source performance-quick "$PYTHON" -m app.evaluation.performance_benchmark \
    --profile quick --repetitions 3 --database "$RUN_ROOT/data/papers.db" --runtime-root "$RUN_ROOT" \
    --out "$WORK/artifacts/performance/performance_quick_results.json" \
    --stage import --stage frontend_build
  run_in_source performance-quick-validation "$PYTHON" -m app.evaluation.performance_validator \
    "$WORK/artifacts/performance/performance_quick_results.json" \
    --expected-profile quick --expected-repetitions 3 --stage import --stage frontend_build \
    --out "$WORK/artifacts/performance/performance_quick_validation.json"
fi

if [[ "$MODE" == "full" ]]; then
  run_logged paper-build make -C "$RUN_ROOT" paper PYTHON="$PYTHON"
  run_logged thesis-build make -C "$RUN_ROOT" thesis PYTHON="$PYTHON"
else
  # Quick mode is an explicit layout/build probe and does not execute the
  # one-time held-out remediation-v2 suite. The generated macros visibly say
  # "not run" and cannot pass final manuscript validation without this flag.
  run_logged paper-layout-build make -C "$RUN_ROOT" paper-layout PYTHON="$PYTHON"
  run_logged thesis-layout-assets make -C "$RUN_ROOT" thesis-assets-layout PYTHON="$PYTHON"
  run_logged thesis-build make -C "$RUN_ROOT" thesis-compile PYTHON="$PYTHON"
fi
if [[ "$MODE" == "full" ]]; then
  run_in_source manuscript-preflight "$PYTHON" scripts/validate_manuscripts.py \
    --json-out "$WORK/artifacts/manuscript_preflight.json"
else
  run_in_source manuscript-layout-preflight "$PYTHON" scripts/validate_manuscripts.py \
    --allow-v2-not-run --json-out "$WORK/artifacts/manuscript_preflight.json"
fi
for document in ieee-paper thesis; do
  pdf="$RUN_ROOT/build/${document}.pdf"
  [[ -s "$pdf" ]] || die "missing compiled PDF: $pdf"
  run_logged "qpdf-${document}" qpdf --check "$pdf"
  run_logged "pdfinfo-${document}" pdfinfo "$pdf"
  run_logged "pdffonts-${document}" pdffonts "$pdf"
  text_file="$WORK/artifacts/${document}.txt"
  pdftotext "$pdf" "$text_file"
  if rg -n 'AUTHOR INPUT REQUIRED|PLACEHOLDER|TODO' "$text_file"; then
    die "visible placeholder marker found in $document"
  fi
  mkdir -p "$WORK/artifacts/rendered/${document}"
  pdftoppm -png -r 120 "$pdf" "$WORK/artifacts/rendered/${document}/page" >/dev/null 2>&1
  PAGE_COUNT="$(find "$WORK/artifacts/rendered/${document}" -type f -name 'page-*.png' | wc -l)"
  EXPECTED_PAGES="$(pdfinfo "$pdf" | awk '/^Pages:/ {print $2}')"
  [[ "$PAGE_COUNT" == "$EXPECTED_PAGES" ]] || die "rendered page count mismatch for $document"
done

run_in_source reproduced-release-build "$PYTHON" -m app.reproducibility.release build \
  --version "${RELEASE_VERSION}-reproduced" --out-dir "$WORK/artifacts/reproduced_release_bundle" \
  --evidence-dir "$WORK/artifacts/reproduced_release" --allow-dirty
REPRODUCED_RELEASE_ARCHIVE="$WORK/artifacts/reproduced_release_bundle/ttlab-research-advisor-${RELEASE_VERSION}-reproduced-${SOURCE_COMMIT:0:12}.tar.gz"
run_in_source reproduced-release-verify "$PYTHON" -m app.reproducibility.release verify \
  "$REPRODUCED_RELEASE_ARCHIVE"

log "final reproduction manifest (no further files are created inside the reproduction workspace)"
(cd "$RUN_ROOT" && "$PYTHON" -m app.reproducibility.manifest \
  --root "$RUN_ROOT" --work "$WORK" --mode "$MODE" --out "$WORK/reproduction_manifest.json" \
  --source-commit "$SOURCE_COMMIT" --source-tree "$SOURCE_TREE" --source-clean-at-start)

log "independent reproduction checksum verification"
(cd "$WORK" && sha256sum -c --quiet REPRODUCTION_SHA256SUMS)
printf 'checksums=valid\n'

if [[ -n "$RETAIN_DIR" ]]; then
  log "retain verified content-free reproduction evidence"
  "$PYTHON" "$RUN_ROOT/scripts/retain_reproduction_evidence.py" \
    --work-dir "$WORK" --out-dir "$RETAIN_DIR" \
    --expected-commit "$SOURCE_COMMIT" --expected-tree "$SOURCE_TREE"
fi

log "Reproduction completed: mode=$MODE source_commit=$SOURCE_COMMIT work=$WORK"
if ((KEEP_WORK == 0)); then
  verify_workspace_ownership
  git -C "$ROOT" worktree remove --force "$RUN_ROOT"
  [[ ! -e "$RUN_ROOT" ]] || die "detached worktree removal did not complete; refusing workspace cleanup"
  verify_workspace_ownership
  rm -rf --one-file-system -- "$WORK"
  log "Removed reproduction workspace."
fi
