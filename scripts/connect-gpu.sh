#!/usr/bin/env bash
# Local backend + frontend pointing at a remote OCR+LLM service on the GPU box.
#
#   bash scripts/connect-gpu.sh <gpu-host:port> <OCR_API_KEY> [BACKEND_API_TOKEN] [--no-tmux]
#
# Examples:
#   bash scripts/connect-gpu.sh 151.115.85.153:8000 <OCR_API_KEY> <BACKEND_TOKEN>
#   bash scripts/connect-gpu.sh '[2001:bc8:1d90::1]:8000' <OCR_API_KEY> <BACKEND_TOKEN>
#
# By default backend and Vite run in a detached tmux session `o2j-connect`.
# Use --no-tmux to keep them as child processes of this shell (Ctrl-C stops).
# If BACKEND_API_TOKEN is omitted, one is generated and printed. The OCR key
# and backend token are different secrets; do not reuse the same value.

set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

USE_TMUX=1
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --tmux) USE_TMUX=1 ;;
    --no-tmux) USE_TMUX=0 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) ARGS+=("$arg") ;;
  esac
done
set -- "${ARGS[@]:-}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "[connect-gpu] tmux not found; falling back to background processes" >&2
  USE_TMUX=0
fi

OCR_HOSTPORT="${1:?usage: connect-gpu.sh <gpu-host:port> <OCR_API_KEY> [BACKEND_API_TOKEN] [--no-tmux]}"
OCR_KEY="${2:?usage: connect-gpu.sh <gpu-host:port> <OCR_API_KEY> [BACKEND_API_TOKEN] [--no-tmux]}"

# Accept IPv6 without brackets and normalize it to [addr]:port.
if [[ "$OCR_HOSTPORT" != \[* && "$(tr -cd ':' <<< "$OCR_HOSTPORT" | wc -c)" -gt 1 ]]; then
  OCR_HOSTPORT="[${OCR_HOSTPORT%:*}]${OCR_HOSTPORT##*:}"
fi

API_TOKEN="${3:-${API_TOKEN:-}}"
GENERATED_TOKEN=0
if [[ -z "$API_TOKEN" ]]; then
  API_TOKEN="$(openssl rand -hex 32)"
  GENERATED_TOKEN=1
fi

export WEB_OCR_BACKEND=remote
export OCR_SERVICE_URL="http://${OCR_HOSTPORT}"
export OCR_SERVICE_KEY="$OCR_KEY"
export API_TOKEN
export O2J_API_TOKEN="$API_TOKEN"
export O2J_API_TARGET="http://127.0.0.1:8000"
export O2J_DB_PATH="${O2J_DB_PATH:-work/o2j.db}"
export PYTHONPATH="src:."

mkdir -p work

wait_for() {
  local url="$1" name="$2" tries="${3:-30}"
  for ((i = 0; i < tries; i++)); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null || [[ $? == 22 ]]; then
      echo "[connect-gpu] $name ready"
      return 0
    fi
    sleep 1
  done
  echo "[connect-gpu] $name did not respond" >&2
  return 1
}

echo "[connect-gpu] backend:  http://127.0.0.1:8000"
echo "[connect-gpu] OCR+LLM:  ${OCR_SERVICE_URL}"
echo "[connect-gpu] frontend: http://localhost:3000"
if [[ "$GENERATED_TOKEN" == "1" ]]; then
  echo
  echo "[connect-gpu] generated BACKEND_API_TOKEN (use it for CLI/web):"
  echo "$API_TOKEN"
  echo
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "[connect-gpu] installing frontend dependencies ..."
  (cd frontend && npm install)
fi

if [[ "$USE_TMUX" == "1" ]]; then
  SESSION="o2j-connect"
  tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"

  tmux new-session -d -s "$SESSION" -n backend \
    "cd \"$REPO_ROOT\" && exec uv run --extra serve uvicorn backend.main:app --host 127.0.0.1 --port 8000"
  wait_for "http://127.0.0.1:8000/api/health" "backend" 30

  tmux new-window -t "$SESSION" -n frontend \
    "cd \"$REPO_ROOT/frontend\" && exec npm run dev"

  echo
  echo "[connect-gpu] tmux session: ${SESSION}"
  echo "[connect-gpu] attach: tmux attach -t ${SESSION}"
  echo "[connect-gpu] stop:   tmux kill-session -t ${SESSION}"
  exit 0
fi

PIDS=()
cleanup() {
  echo
  echo "[connect-gpu] stopping ..."
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv run --extra serve uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
PIDS+=($!)
wait_for "http://127.0.0.1:8000/api/health" "backend" 30

(cd frontend && npm run dev) &
PIDS+=($!)

echo "[connect-gpu] ready. Ctrl-C stops both processes."
wait
