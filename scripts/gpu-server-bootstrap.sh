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

OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
OCR_LLM_MODEL=qwen3-8b-l4 \
uv run --extra gpu --extra serve ocr-api serve --host 0.0.0.0 --port 8000 &
OCR_PID=$!

trap 'kill "$LLM_PID" "$OCR_PID" 2>/dev/null || true' EXIT INT TERM

until curl -fsS -o /dev/null http://localhost:8000/health; do sleep 2; done
IP="$(curl -fsS ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "=== skopiuj na klienta: ============================================"
echo "bash scripts/connect-gpu.sh ${IP}:8000 ${API_KEY}"
echo "====================================================================="
echo

wait
