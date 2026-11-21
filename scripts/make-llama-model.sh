#!/usr/bin/env bash
# Build full-BF16 llama.cpp weights for lightonai/LightOnOCR-3-4B.
# No quantized GGUF is produced. The mmproj stays in its published F16 form.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/LightOnOCR-3-4B"
GGUF="$ROOT/models/LightOnOCR-3-4B-BF16.gguf"
MMPROJ="$ROOT/models/mmproj-LightOnOCR-3-4B-F16.gguf"
LLAMA_CPP="${LLAMA_CPP_DIR:-$ROOT/llama.cpp}"

mkdir -p "$ROOT/models"

if [ ! -f "$MODEL_DIR/config.json" ]; then
  huggingface-cli download lightonai/LightOnOCR-3-4B --local-dir "$MODEL_DIR"
fi

if [ ! -f "$GGUF" ]; then
  python "$LLAMA_CPP/convert_hf_to_gguf.py" "$MODEL_DIR" \
    --outfile "$GGUF" --outtype bf16
fi

if [ ! -f "$MMPROJ" ]; then
  huggingface-cli download richardyoung/LightOnOCR-3-4B-GGUF \
    mmproj-LightOnOCR-3-4B-F16.gguf --local-dir "$ROOT/models"
  if [ -f "$ROOT/models/mmproj-LightOnOCR-3-4B-F16.gguf" ] && [ ! -f "$MMPROJ" ]; then
    mv "$ROOT/models/mmproj-LightOnOCR-3-4B-F16.gguf" "$MMPROJ"
  fi
fi

echo "$GGUF"
echo "$MMPROJ"
