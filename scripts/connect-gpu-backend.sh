#!/usr/bin/env bash
# Terminal 1: local backend that forwards OCR+LLM to a remote GPU box.
#
#   bash scripts/connect-gpu-backend.sh <gpu-host:port> <OCR_API_KEY> <BACKEND_API_TOKEN>
#
# Examples:
#   bash scripts/connect-gpu-backend.sh 151.115.85.153:8000 <OCR_KEY> <TOKEN>
#   bash scripts/connect-gpu-backend.sh '[2001:bc8:1d90::1]:8000' <OCR_KEY> <TOKEN>

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,9p' "$0"
  exit 0
fi

OCR_HOSTPORT="${1:?usage: connect-gpu-backend.sh <gpu-host:port> <OCR_API_KEY> <BACKEND_API_TOKEN>}"
OCR_KEY="${2:?usage: connect-gpu-backend.sh <gpu-host:port> <OCR_API_KEY> <BACKEND_API_TOKEN>}"
API_TOKEN="${3:?usage: connect-gpu-backend.sh <gpu-host:port> <OCR_API_KEY> <BACKEND_API_TOKEN>}"

# Accept IPv6 without brackets and normalize it to [addr]:port.
if [[ "$OCR_HOSTPORT" != \[* && "$(tr -cd ':' <<< "$OCR_HOSTPORT" | wc -c)" -gt 1 ]]; then
  OCR_HOSTPORT="[${OCR_HOSTPORT%:*}]${OCR_HOSTPORT##*:}"
fi

export WEB_OCR_BACKEND=remote
export OCR_SERVICE_URL="http://${OCR_HOSTPORT}"
export OCR_SERVICE_KEY="$OCR_KEY"
export API_TOKEN="$API_TOKEN"
export O2J_DB_PATH="${O2J_DB_PATH:-work/o2j.db}"
export PYTHONPATH="src:."

mkdir -p work

echo "[backend] local:  http://127.0.0.1:8000"
echo "[backend] OCR+LLM: ${OCR_SERVICE_URL}"
exec uv run --extra serve uvicorn backend.main:app --host 127.0.0.1 --port 8000
