#!/usr/bin/env bash
# Start serwerów na wynajętym GPU -- dokładnie te komendy, które odpalaliśmy
# ręcznie w tmux: lab serve (LLM) + ocr-api serve (OCR), bez Dockera.
# Klient dostaje wyłącznie adres IPv4 i endpoint http://.
#
#   bash scripts/gpu-server-bootstrap.sh

set -euo pipefail
cd "$(dirname "$0")/.."

uv run lab serve --model qwen3-8b-l4 &
LLM_PID=$!

source .env
: "${API_KEY:?API_KEY must be set in .env on the GPU box}"

BACKEND_TOKEN="$(openssl rand -hex 32)"

OCR_FORCE_IMAGE="${OCR_FORCE_IMAGE:-1}" \
OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
OCR_LLM_MODEL=qwen3-8b-l4 \
uv run --extra gpu --extra serve ocr-api serve --host 0.0.0.0 --port 8000 &
OCR_PID=$!

trap 'kill "$LLM_PID" "$OCR_PID" 2>/dev/null || true' EXIT INT TERM

until curl -fsS -o /dev/null http://localhost:8000/health; do sleep 2; done
IP="$(curl -4 -fsS https://api.ipify.org 2>/dev/null \
  || curl -4 -fsS https://ipv4.icanhazip.com 2>/dev/null \
  || hostname -I | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) {print $i; exit}}')"
IP="$(printf '%s' "$IP" | tr -d '[:space:]')"
if [[ ! "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: could not determine a public IPv4 address" >&2
  exit 1
fi
echo
echo "=== terminal 1 — backend (na kliencie): ============================="
echo "bash scripts/connect-gpu-backend.sh ${IP}:8000 ${API_KEY} ${BACKEND_TOKEN}"
echo
echo "=== terminal 2 — frontend (na kliencie): ============================"
echo "bash scripts/connect-gpu-frontend.sh ${BACKEND_TOKEN}"
echo "====================================================================="
echo "BACKEND_API_TOKEN (zapisz go, użyj also w CLI):"
echo "${BACKEND_TOKEN}"
echo

wait
