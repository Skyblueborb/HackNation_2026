#!/usr/bin/env bash
# Install CUDA 13.2 toolkit and optimized Qwen3.5 kernels on the NVIDIA box.
#
# Run as root on the L4 machine:
#   bash scripts/gpu-install-kernels.sh
#
# Fixes conflicting NVIDIA apt sources, installs CUDA 13.2, then rebuilds
# causal-conv1d and flash-linear-attention against the torch CUDA version.

set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash scripts/gpu-install-kernels.sh)" >&2
  exit 2
fi

BACKUP_DIR=/root/apt-backup
mkdir -p "$BACKUP_DIR"

echo "[kernels] moving old CUDA apt sources to $BACKUP_DIR"
for source_file in /etc/apt/sources.list.d/*cuda*; do
  [[ -e "$source_file" ]] || continue
  mv "$source_file" "$BACKUP_DIR/"
done

echo "[kernels] installing cuda-keyring"
KEYRING=/tmp/cuda-keyring_1.1-1_all.deb
wget -q -O "$KEYRING" \
  https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i "$KEYRING"

echo "[kernels] apt update"
apt-get update

echo "[kernels] installing CUDA 13.2 toolkit and build tools"
apt-get install -y wget build-essential ninja-build cuda-toolkit-13-2

export CUDA_HOME=/usr/local/cuda-13.2
export PATH="$CUDA_HOME/bin:$PATH"

NVCC_VERSION="$(nvcc --version | grep -o 'release [0-9]\+\.[0-9]\+' | head -1 || true)"
echo "[kernels] nvcc: ${NVCC_VERSION:-unknown}"
if [[ "$NVCC_VERSION" != "release 13.2" ]]; then
  echo "ERROR: nvcc is not CUDA 13.2; cannot build kernels for torch cu13.2" >&2
  echo "Check: ls -d /usr/local/cuda* ; which nvcc" >&2
  exit 1
fi

echo "[kernels] installing Python build deps"
uv pip install --python "$REPO_ROOT/.venv/bin/python" ninja packaging

echo "[kernels] building causal-conv1d"
uv pip install --python "$REPO_ROOT/.venv/bin/python" \
  causal-conv1d --no-build-isolation --reinstall

echo "[kernels] installing flash-linear-attention"
uv pip install --python "$REPO_ROOT/.venv/bin/python" \
  flash-linear-attention --reinstall

echo "[kernels] verifying"
"$REPO_ROOT/.venv/bin/python" -c "import causal_conv1d, fla; print('kernels ok')"

echo
echo "[kernels] done. Restart the GPU stack:"
echo "  bash scripts/gpu-server-bootstrap.sh"
