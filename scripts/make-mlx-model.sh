#!/usr/bin/env bash
# Download the mlx-vlm 8-bit conversion of LightOnOCR-3-4B, vision tower included.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/models/LightOnOCR-3-4B-mlx-8bit"
REPO="prithivMLmods/LightOnOCR-3-4B-MLX"

mkdir -p "$OUT"

if [ ! -f "$OUT/model.safetensors" ]; then
  uv run --extra local --extra serve hf download "$REPO" \
    8bit/model.safetensors 8bit/model.safetensors.index.json \
    8bit/config.json 8bit/generation_config.json \
    8bit/tokenizer.json 8bit/tokenizer_config.json 8bit/vocab.json \
    8bit/preprocessor_config.json 8bit/processor_config.json \
    --local-dir "$OUT"
  cp "$OUT/8bit/"* "$OUT/"
fi

echo "$OUT"
