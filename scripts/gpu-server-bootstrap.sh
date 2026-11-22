#!/usr/bin/env bash
# Start serwerów na wynajętym GPU -- dokładnie te komendy, które odpalaliśmy
# ręcznie w tmux: lab serve (LLM) + ocr-api serve (OCR), bez Dockera.
#
#   bash scripts/gpu-server-bootstrap.sh

set -euo pipefail
cd "$(dirname "$0")/.."

uv run lab serve --model qwen3-8b-l4 &
LLM_PID=$!

source .env
: "${API_KEY:?API_KEY must be set in .env on the GPU box}"

BACKEND_TOKEN="$(openssl rand -hex 32)"

OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
OCR_LLM_MODEL=qwen3-8b-l4 \
uv run --extra gpu --extra serve ocr-api serve --host 0.0.0.0 --port 8000 &
OCR_PID=$!

trap 'kill "$LLM_PID" "$OCR_PID" 2>/dev/null || true' EXIT INT TERM

until curl -fsS -o /dev/null http://localhost:8000/health; do sleep 2; done
IP="$(curl -fsS ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "=== skopiuj na klienta: ============================================"
echo "bash scripts/connect-gpu.sh ${IP}:8000 ${API_KEY} ${BACKEND_TOKEN}"
echo "====================================================================="
echo "BACKEND_API_TOKEN (zapisz go, użyj also w CLI):"
echo "${BACKEND_TOKEN}"
echo

wait
