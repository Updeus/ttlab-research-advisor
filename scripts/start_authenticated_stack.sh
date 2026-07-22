#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:5173"
OLLAMA_URL="http://127.0.0.1:11434"
STARTED_PIDS=()

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if ((${#STARTED_PIDS[@]})); then
    log "Stopping services started by this launcher..."
    kill "${STARTED_PIDS[@]}" >/dev/null 2>&1 || true
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="$3"
  local response_file
  response_file="$(mktemp)"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS --connect-timeout 1 --max-time 3 "$url" >"$response_file" 2>/dev/null; then
      rm -f "$response_file"
      log "$label is ready at $url"
      return 0
    fi
    sleep 1
  done
  rm -f "$response_file"
  die "$label did not become ready at $url"
}

trap cleanup EXIT
trap 'exit 130' INT TERM

[[ -x .venv/bin/python ]] || die "Missing .venv/bin/python. Run the project dependency setup first."
command -v npm >/dev/null 2>&1 || die "npm is not installed or not on PATH."
command -v curl >/dev/null 2>&1 || die "curl is not installed or not on PATH."

log "Checking administrator accounts..."
ADMIN_LIST="$(PYTHONPATH=backend .venv/bin/python -m app.admin_cli list)"
if [[ -z "${ADMIN_LIST//[[:space:]]/}" ]]; then
  printf 'No administrator exists. Create the first administrator now.\n'
  PYTHONPATH=backend .venv/bin/python -m app.admin_cli create jarod --display-name "Jarod"
else
  printf '%s\n' "$ADMIN_LIST"
  log "An administrator already exists; skipping one-time account creation."
fi

if curl -fsS --connect-timeout 1 --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  log "Ollama is already running; reusing it."
else
  command -v ollama >/dev/null 2>&1 || die "Ollama is not installed or not on PATH."
  log "Starting private local Ollama..."
  OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_NO_CLOUD=1 \
    OLLAMA_NUM_PARALLEL=1 \
    ollama serve &
  STARTED_PIDS+=("$!")
  wait_for_url "Ollama" "$OLLAMA_URL/api/tags" 60
fi

log "Installed Ollama inventory:"
curl -fsS "$OLLAMA_URL/api/tags"
printf '\n'

if curl -fsS --connect-timeout 1 --max-time 3 "$BACKEND_URL/health" >/dev/null 2>&1; then
  log "Backend is already running; reusing it."
else
  log "Starting authenticated local backend..."
  TTLAB_SECURITY_MODE=local_demo \
    TTLAB_ALLOW_INSECURE_LOCAL_DEMO=false \
    TTLAB_DEMO_CORPUS_PREVIEW=true \
    TTLAB_SERVICE_ROLE=api \
    TTLAB_SYNC_EXECUTION_MODE=disabled \
    TTLAB_SYNC_ENABLED=true \
    TTLAB_OLLAMA_BASE_URL="$OLLAMA_URL" \
    TTLAB_ALLOWED_LLM_PROVIDERS='["offline_extractive","ollama"]' \
    PYTHONPATH=backend \
    .venv/bin/python -m uvicorn app.main:app \
      --app-dir backend \
      --host 127.0.0.1 \
      --port 8000 &
  STARTED_PIDS+=("$!")
  wait_for_url "Backend" "$BACKEND_URL/health" 120
fi

log "Checking backend readiness..."
if ! curl -fsS --connect-timeout 2 --max-time 10 "$BACKEND_URL/ready"; then
  printf '\nWARNING: The backend is live but not ready. Review the readiness response and index status above.\n' >&2
else
  printf '\n'
fi

log "Building the frontend production bundle..."
VITE_API_BASE="$BACKEND_URL" npm --prefix frontend run build

if curl -fsS --connect-timeout 1 --max-time 3 "$FRONTEND_URL" >/dev/null 2>&1; then
  log "Frontend is already running; reusing it."
else
  log "Serving the frontend production bundle..."
  npm --prefix frontend run preview -- \
    --host 127.0.0.1 \
    --port 5173 \
    --strictPort &
  STARTED_PIDS+=("$!")
  wait_for_url "Frontend" "$FRONTEND_URL" 60
fi

printf '\nAuthenticated TTLAB stack is ready.\n'
printf '  Frontend: %s\n' "$FRONTEND_URL"
printf '  Admin:    %s/admin\n' "$FRONTEND_URL"
printf '  Backend:  %s\n' "$BACKEND_URL"
printf '  Ollama:   %s\n' "$OLLAMA_URL"

if ((${#STARTED_PIDS[@]})); then
  printf '\nPress Ctrl+C to stop only the services started by this launcher.\n'
  wait "${STARTED_PIDS[@]}"
else
  printf '\nAll services were already running; this launcher did not start new processes.\n'
fi
