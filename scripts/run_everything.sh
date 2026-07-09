#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LIMIT=25
INSTALL=1
PREPARE=1
VERIFY=1
SERVE=1
SKIP_DOWNLOADS=0
SKIP_ARTIFACTS=0
BACKEND_PORT=8000
FRONTEND_PORT=5173
START_OLLAMA=1
OLLAMA_URL="${TTLAB_OLLAMA_BASE_URL:-${OLLAMA_BASE_URL:-http://127.0.0.1:11434}}"
OLLAMA_START_TIMEOUT=45
STARTED_PIDS=()

usage() {
  cat <<'USAGE'
Run the TTLAB Research Intelligence Platform end to end.

Usage:
  ./scripts/run_everything.sh [options]

Default behavior:
  1. Create/use .venv and install backend dependencies.
  2. Run npm install for the frontend.
  3. Prepare a bounded local demo dataset.
  4. Run backend tests, frontend build, and backend smoke check.
  5. Start/reuse Ollama, backend, and frontend dev servers.

Options:
  --limit N           Demo preparation limit. Default: 25.
  --backend-port N    Backend port. Default: 8000.
  --frontend-port N   Frontend port. Default: 5173.
  --ollama-url URL    Ollama base URL. Default: http://127.0.0.1:11434.
  --ollama-timeout N  Seconds to wait for Ollama startup. Default: 45.
  --skip-downloads    Do not attempt PDF downloads during demo prep.
  --skip-artifacts    Do not generate sample paper artifacts during demo prep.
  --no-ollama         Do not check/start Ollama. Ask TTLAB will use fallback behavior if needed.
  --no-install        Skip backend/frontend dependency install.
  --no-prepare        Skip demo preparation.
  --no-verify         Skip pytest, frontend build, and smoke check.
  --no-serve          Do not start dev servers.
  --prepare-only      Only install dependencies and prepare demo data.
  --verify-only       Only install dependencies and run verification.
  --serve-only        Only start/reuse backend and frontend dev servers.
  -h, --help          Show this help text.

Useful examples:
  ./scripts/run_everything.sh
  ./scripts/run_everything.sh --skip-downloads
  ./scripts/run_everything.sh --serve-only
  ./scripts/run_everything.sh --serve-only --no-ollama
  ./scripts/run_everything.sh --verify-only
USAGE
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if ((${#STARTED_PIDS[@]})); then
    log "Stopping services started by this script..."
    kill "${STARTED_PIDS[@]}" >/dev/null 2>&1 || true
    STARTED_PIDS=()
  fi
}

trap cleanup EXIT
trap 'exit 130' INT TERM

while (($#)); do
  case "$1" in
    --limit)
      LIMIT="${2:-}"
      [[ "$LIMIT" =~ ^[0-9]+$ ]] || die "--limit requires a positive integer"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="${2:-}"
      [[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || die "--backend-port requires a port number"
      shift 2
      ;;
    --frontend-port)
      FRONTEND_PORT="${2:-}"
      [[ "$FRONTEND_PORT" =~ ^[0-9]+$ ]] || die "--frontend-port requires a port number"
      shift 2
      ;;
    --ollama-url)
      OLLAMA_URL="${2:-}"
      [[ -n "$OLLAMA_URL" ]] || die "--ollama-url requires a URL"
      shift 2
      ;;
    --ollama-timeout)
      OLLAMA_START_TIMEOUT="${2:-}"
      [[ "$OLLAMA_START_TIMEOUT" =~ ^[0-9]+$ ]] || die "--ollama-timeout requires a positive integer"
      shift 2
      ;;
    --skip-downloads)
      SKIP_DOWNLOADS=1
      shift
      ;;
    --skip-artifacts)
      SKIP_ARTIFACTS=1
      shift
      ;;
    --no-ollama)
      START_OLLAMA=0
      shift
      ;;
    --no-install)
      INSTALL=0
      shift
      ;;
    --no-prepare)
      PREPARE=0
      shift
      ;;
    --no-verify)
      VERIFY=0
      shift
      ;;
    --no-serve)
      SERVE=0
      shift
      ;;
    --prepare-only)
      PREPARE=1
      VERIFY=0
      SERVE=0
      shift
      ;;
    --verify-only)
      PREPARE=0
      VERIFY=1
      SERVE=0
      shift
      ;;
    --serve-only)
      INSTALL=0
      PREPARE=0
      VERIFY=0
      SERVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

if [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
  [[ -n "$PYTHON_BIN" ]] || die "Python was not found on PATH."
  log "Creating Python virtual environment at .venv..."
  "$PYTHON_BIN" -m venv .venv
  PYTHON=".venv/bin/python"
fi

[[ -x "$PYTHON" ]] || die "Unable to find .venv/bin/python."
command -v npm >/dev/null 2>&1 || die "npm was not found on PATH."

OLLAMA_URL="${OLLAMA_URL%/}"

if ((INSTALL)); then
  log "Installing backend dependencies..."
  "$PYTHON" -m pip install -r backend/requirements.txt

  log "Installing frontend dependencies..."
  (cd frontend && npm install)
else
  log "Skipping dependency install."
fi

if ((PREPARE)); then
  log "Preparing bounded local demo data with limit=${LIMIT}..."
  PREPARE_ARGS=(--limit "$LIMIT")
  ((SKIP_DOWNLOADS)) && PREPARE_ARGS+=(--skip-downloads)
  ((SKIP_ARTIFACTS)) && PREPARE_ARGS+=(--skip-artifacts)
  PYTHONPATH=backend "$PYTHON" -m app.demo.prepare_demo "${PREPARE_ARGS[@]}"
else
  log "Skipping demo preparation."
fi

if ((VERIFY)); then
  log "Running backend tests..."
  PYTHONPATH=backend "$PYTHON" -m pytest

  log "Building frontend..."
  (cd frontend && npm run build)

  log "Running backend smoke check..."
  PYTHONPATH=backend "$PYTHON" -m app.demo.smoke_check
else
  log "Skipping verification."
fi

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="${3:-45}"
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$label is ready at $url"
      return 0
    fi
    sleep 1
  done
  die "$label did not become ready at $url"
}

ollama_host_from_url() {
  local url="$1"
  url="${url#http://}"
  url="${url#https://}"
  url="${url%%/*}"
  printf '%s' "$url"
}

ensure_ollama() {
  local tags_url="${OLLAMA_URL}/api/tags"

  if ! ((START_OLLAMA)); then
    log "Skipping Ollama startup/check."
    return 0
  fi

  if curl -fsS "$tags_url" >/dev/null 2>&1; then
    log "Ollama already running at ${OLLAMA_URL}; reusing it."
    return 0
  fi

  command -v ollama >/dev/null 2>&1 || die "Ollama is not installed or not on PATH. Install/start Ollama, or rerun with --no-ollama to use offline fallback behavior."

  local ollama_host
  ollama_host="$(ollama_host_from_url "$OLLAMA_URL")"
  [[ -n "$ollama_host" ]] || die "Could not derive OLLAMA_HOST from --ollama-url ${OLLAMA_URL}"

  log "Starting Ollama at ${OLLAMA_URL}..."
  OLLAMA_HOST="$ollama_host" ollama serve &
  STARTED_PIDS+=("$!")
  wait_for_url "Ollama" "$tags_url" "$OLLAMA_START_TIMEOUT"
}

if ((SERVE)); then
  BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
  FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

  ensure_ollama

  if curl -fsS "${BACKEND_URL}/health" >/dev/null 2>&1; then
    log "Backend already running at ${BACKEND_URL}; reusing it."
  else
    log "Starting backend at ${BACKEND_URL}..."
    TTLAB_OLLAMA_BASE_URL="$OLLAMA_URL" PYTHONPATH=backend "$PYTHON" -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT" &
    STARTED_PIDS+=("$!")
    wait_for_url "Backend" "${BACKEND_URL}/health"
  fi

  if curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
    log "Frontend already running at ${FRONTEND_URL}; reusing it."
  else
    log "Starting frontend at ${FRONTEND_URL}..."
    (cd frontend && VITE_API_BASE="$BACKEND_URL" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort) &
    STARTED_PIDS+=("$!")
    wait_for_url "Frontend" "$FRONTEND_URL"
  fi

  printf '\nReady.\n'
  printf '  Frontend: %s\n' "$FRONTEND_URL"
  printf '  Backend:  %s\n' "$BACKEND_URL"
  printf '  Ollama:   %s\n' "$OLLAMA_URL"
  printf '  API docs: %s/docs\n' "$BACKEND_URL"

  if ((${#STARTED_PIDS[@]})); then
    printf '\nPress Ctrl+C to stop servers started by this script.\n'
    wait "${STARTED_PIDS[@]}"
  else
    printf '\nBoth servers were already running; nothing was started by this script.\n'
  fi
else
  log "Skipping dev server startup."
fi
