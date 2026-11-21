#!/usr/bin/env bash
# One-time trial: download the 8-bit MLX conversion of LightOnOCR-3-0.8B.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/models/LightOnOCR-3-0.8B-mlx-8bit"
REPO="fwgpiyawudk/LightOnOCR-3-0.8B-MLX-8bit"

mkdir -p "$OUT"

if [ ! -f "$OUT/model.safetensors" ]; then
  uv run --extra local --extra serve hf download "$REPO" \
    model.safetensors model.safetensors.index.json config.json \
    generation_config.json chat_template.jinja \
    tokenizer.json tokenizer_config.json vocab.json \
    preprocessor_config.json processor_config.json \
    --local-dir "$OUT"
fi

echo "$OUT"
