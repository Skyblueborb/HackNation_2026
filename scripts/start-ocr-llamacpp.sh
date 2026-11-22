#!/usr/bin/env bash
# Start multimodal llama.cpp OCR server on the L4 box (CUDA, port 8083).
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${OCR_CPP_GGUF:-models/llamacpp/LightOnOCR-3-0.8B.Q4_K_M.gguf}"
MMPROJ="${OCR_CPP_MMPROJ:-models/llamacpp/LightOnOCR-3-0.8B.mmproj-q8_0.gguf}"
PORT="${OCR_CPP_PORT:-8083}"

if [[ ! -f "$MODEL" || ! -f "$MMPROJ" ]]; then
  echo "missing GGUF files; run: bash scripts/download-ocr-llamacpp.sh" >&2
  exit 2
fi

exec llama-server \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  --host 127.0.0.1 \
  --port "$PORT" \
  -c 8192 \
  -ngl 99 \
  -fa on \
  --image-min-tokens 1024 \
  --reasoning off \
  --reasoning-budget 0 \
  --chat-template-kwargs '{"enable_thinking":false}' \
  --parallel 1
