#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Fast repeat launcher: reuse the prepared corpus and installed dependencies,
# while starting/reusing Ollama, FastAPI, and Vite on their loopback ports.
exec "$ROOT_DIR/scripts/run_everything.sh" --serve-only "$@"
