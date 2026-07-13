#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="full"
WORK=""
INSTALL=0
KEEP_WORK=1
RELEASE_VERSION="0.1.0-remediation"
SOURCE_DB="$ROOT/data/papers.db"
PYTHON="$ROOT/.venv/bin/python"

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
    --discard-work) KEEP_WORK=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$MODE" == "quick" || "$MODE" == "full" ]] || die "--mode must be quick or full"
[[ -n "$WORK" ]] || WORK="$ROOT/tmp/reproduce/$MODE"
mkdir -p "$WORK/logs" "$WORK/artifacts" "$WORK/data/indexes" "$WORK/data/extracted_text" "$WORK/data/chunks"
WORK="$(cd "$WORK" && pwd)"
SOURCE_DB="$(realpath -m "$SOURCE_DB")"

command -v git >/dev/null || die "git is required"
command -v npm >/dev/null || die "npm is required"
command -v node >/dev/null || die "node is required"
command -v qpdf >/dev/null || die "qpdf is required for PDF preflight"
command -v pdfinfo >/dev/null || die "pdfinfo is required for PDF preflight"
command -v pdffonts >/dev/null || die "pdffonts is required for PDF preflight"
command -v pdftotext >/dev/null || die "pdftotext is required for PDF preflight"
command -v pdftoppm >/dev/null || die "pdftoppm is required for page rendering"
[[ -x "$PYTHON" ]] || die "missing .venv/bin/python; create the pinned environment first or use --install after creating .venv"

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

if ((INSTALL)); then
  run_logged install-python "$PYTHON" -m pip install -r "$ROOT/backend/requirements.txt" -r "$ROOT/backend/requirements-dense.txt" -r "$ROOT/backend/requirements-ocr.txt"
  run_logged install-frontend npm --prefix "$ROOT/frontend" ci
fi

run_logged dependency-imports env PYTHONPATH="$ROOT/backend" "$PYTHON" -c \
  'import fastapi,httpx,jsonschema,fitz,sqlmodel; import sentence_transformers,torch; print("python-dependencies=ready")'
run_logged external-sanity env PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.evaluation.external_sanity \
  --out-dir "$WORK/artifacts/external_sanity"

run_logged backend-tests env PYTHONPATH="$ROOT/backend" "$PYTHON" -m pytest
run_logged frontend-unit npm --prefix "$ROOT/frontend" test
run_logged frontend-build npm --prefix "$ROOT/frontend" run build
run_logged frontend-e2e npm --prefix "$ROOT/frontend" run test:e2e

if [[ "$MODE" == "full" ]]; then
  [[ -s "$SOURCE_DB" ]] || die "full mode requires an authorized source database: $SOURCE_DB"
  PDF_COUNT="$(find "$ROOT/data/pdfs" -maxdepth 1 -type f -name '*.pdf' | wc -l)"
  ((PDF_COUNT > 0)) || die "full mode requires separately authorized local PDFs under data/pdfs"
  cp "$SOURCE_DB" "$WORK/data/papers.db"
  export TTLAB_DATABASE_URL="sqlite:///$WORK/data/papers.db"
  export PYTHONPATH="$ROOT/backend"

  run_logged seed-import bash -lc "cd '$WORK' && '$PYTHON' -m app.ingestion.manual_import --seed '$ROOT/data/seed/papers.json'"
  run_logged metadata-repair bash -lc "cd '$WORK' && '$PYTHON' -m app.ingestion.metadata_cleaner repair-authors"
  run_logged pdf-identity-audit bash -lc "cd '$WORK' && '$PYTHON' -m app.ingestion.metadata_cleaner audit-pdf-titles"
  run_logged extraction bash -lc "cd '$WORK' && '$PYTHON' -m app.ingestion.pdf_parser extract --overwrite --out-dir '$WORK/data/extracted_text'"
  run_logged chunking bash -lc "cd '$WORK' && '$PYTHON' -m app.indexing.chunker chunk --overwrite --out-dir '$WORK/data/chunks'"
  run_logged keyword-index bash -lc "cd '$WORK' && '$PYTHON' -m app.indexing.keyword_search rebuild"
  run_logged hashing-index bash -lc "cd '$WORK' && '$PYTHON' -m app.indexing.embedder index --provider feature_hashing --out '$WORK/data/indexes/feature_hashing_embeddings.json' --no-status-update"
  run_logged dense-index bash -lc "cd '$WORK' && '$PYTHON' -m app.indexing.embedder index --provider dense --out '$WORK/data/indexes/dense_embeddings.json' --no-status-update --device cpu"

  for retrieval_mode in keyword feature_hashing dense hybrid; do
    run_logged "retrieval-${retrieval_mode}" bash -lc \
      "cd '$WORK' && '$PYTHON' -m app.evaluation.retrieval_eval --questions '$ROOT/data/evaluation/retrieval_silver_v1.jsonl' --mode '$retrieval_mode' --top-k 10 --bootstrap-seed 20260712 --bootstrap-repetitions 10000 --out '$WORK/artifacts/retrieval_${retrieval_mode}.json'"
  done
  run_logged retrieval-label-validator env PYTHONPATH="$ROOT/backend" "$PYTHON" "$ROOT/data/evaluation/validate_retrieval_silver_v1.py"
  run_logged qa-faithfulness-validator env PYTHONPATH="$ROOT/backend" "$PYTHON" "$ROOT/data/evaluation/validate_qa_faithfulness_v1.py"
  run_logged recommendation-proxy bash -lc \
    "cd '$ROOT' && '$PYTHON' -m app.evaluation.recommendation_proxy_eval --profiles '$ROOT/data/evaluation/recommendation_profiles_v1.jsonl' --schema '$ROOT/data/evaluation/recommendation_profiles_v1.schema.json' --prompt '$ROOT/data/evaluation/recommendation_proxy_review_prompt_v1.md' --dense-manifest '$WORK/data/indexes/dense_embeddings.manifest.json' --out-dir '$WORK/artifacts/recommendation_proxy'"
  run_logged recommendation-evidence-validator env PYTHONPATH="$ROOT/backend" "$PYTHON" "$ROOT/data/evaluation/validate_recommendation_proxy_v1.py"
  run_logged topic-author-evidence env PYTHONPATH="$ROOT/backend" "$PYTHON" "$ROOT/data/evaluation/validate_topic_author_silver_v1.py"
  run_logged performance-full bash -lc \
    "cd '$ROOT' && '$PYTHON' -m app.evaluation.performance_benchmark --profile full --database '$WORK/data/papers.db' --runtime-root '$WORK' --out '$WORK/artifacts/performance_results.json'"
else
  export TTLAB_DATABASE_URL="sqlite:///$WORK/data/papers.db"
  run_logged quick-seed-import bash -lc "cd '$WORK' && PYTHONPATH='$ROOT/backend' '$PYTHON' -m app.ingestion.manual_import --seed '$ROOT/data/seed/papers.json'"
  run_logged qa-public-manifest "$PYTHON" -c \
    "import json,pathlib; p=pathlib.Path('$ROOT/artifacts/phase3/qa/qa_faithfulness_manifest_v1.json'); assert json.loads(p.read_text())['status']=='executed_and_validated'; print('qa-public-manifest=valid')"
  run_logged performance-quick env PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.evaluation.performance_benchmark \
    --profile quick --database "$WORK/data/papers.db" --runtime-root "$WORK" --out "$WORK/artifacts/performance_quick.json" \
    --stage import --stage frontend_build
fi

run_logged paper-build make -C "$ROOT" paper
run_logged thesis-build make -C "$ROOT" thesis
for document in ieee-paper thesis; do
  pdf="$ROOT/build/${document}.pdf"
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

run_logged release-build env PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.reproducibility.release build \
  --version "$RELEASE_VERSION" --out-dir "$ROOT/build/releases" --allow-dirty \
  --evidence-dir "$WORK/artifacts/release"
run_logged reproduction-manifest env PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.reproducibility.manifest \
  --root "$ROOT" --work "$WORK" --mode "$MODE" --out "$WORK/reproduction_manifest.json"

log "Reproduction completed: mode=$MODE work=$WORK"
if ((KEEP_WORK == 0)); then
  rm -rf "$WORK"
  log "Removed reproduction workspace."
fi
