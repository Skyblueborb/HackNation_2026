#!/usr/bin/env bash
# Terminal 2: local frontend pointed at the local backend from terminal 1.
#
#   bash scripts/connect-gpu-frontend.sh <BACKEND_API_TOKEN>
#
# Token can also come from O2J_API_TOKEN.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,7p' "$0"
  exit 0
fi

API_TOKEN="${1:-${O2J_API_TOKEN:-}}"
if [[ -z "$API_TOKEN" ]]; then
  echo "usage: connect-gpu-frontend.sh <BACKEND_API_TOKEN>" >&2
  exit 2
fi

export O2J_API_TOKEN="$API_TOKEN"
export O2J_API_TARGET="${O2J_API_TARGET:-http://127.0.0.1:8000}"

if [[ ! -d frontend/node_modules ]]; then
  echo "[frontend] installing dependencies ..."
  (cd frontend && npm install)
fi

echo "[frontend] http://localhost:3000 -> ${O2J_API_TARGET}"
cd frontend
exec npm run dev
