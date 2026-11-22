#!/usr/bin/env bash
# Install the pinned CUDA 13.2 GPU stack from uv.lock on the NVIDIA box.
#
#   cd ~/HackNation_2026
#   bash scripts/gpu-install-kernels.sh
#
# No source builds: pyproject/uv.lock pin torch 2.14.1+cu132, torchvision
# 0.29.1+cu132 and causal-conv1d 1.7.0+cu.13.2.torch.2.14 wheels.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "[kernels] syncing pinned GPU wheels from uv.lock"
uv sync --frozen --extra gpu --extra serve

echo "[kernels] verifying"
.venv/bin/python -c "import torch; print('torch', torch.__version__, torch.version.cuda, torch.cuda.is_available())"
.venv/bin/python -c "import causal_conv1d, fla; print('kernels ok')"

echo
echo "[kernels] done. Restart the GPU stack:"
echo "  bash scripts/gpu-server-bootstrap.sh"
