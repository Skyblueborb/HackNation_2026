#!/usr/bin/env bash
# Download LightOnOCR-3-0.8B GGUF + mmproj for llama.cpp on the GPU box.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="prithivMLmods/LightOnOCR-3-0.8B-GGUF"
MODEL="LightOnOCR-3-0.8B.Q4_K_M.gguf"
MMPROJ="LightOnOCR-3-0.8B.mmproj-q8_0.gguf"
DEST="models/llamacpp"

mkdir -p "$DEST"

uv run python - "$REPO" "$MODEL" "$MMPROJ" "$DEST" <<'PY'
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

repo, model, mmproj, dest = sys.argv[1:]
target = Path(dest)
for filename in (model, mmproj):
    path = hf_hub_download(repo_id=repo, filename=filename, local_dir=target)
    print(path)
PY

echo "downloaded:"
ls -lh "$DEST"
