#!/usr/bin/env bash
# Podłączenie klienta do serwera GPU -- dokładnie te komendy ze screenów:
# lokalny backend wskazuje na publiczny adres ocr-api przez OCR_SERVICE_URL.
#
#   bash scripts/connect-gpu.sh <gpu-ip>:8000 <API_KEY>

set -euo pipefail
cd "$(dirname "$0")/.."

OCR_URL="${1:?użycie: connect-gpu.sh <gpu-ip>:8000 <API_KEY>}"
OCR_KEY="${2:-}"

WEB_OCR_BACKEND=remote \
OCR_SERVICE_URL="http://${OCR_URL}" \
OCR_SERVICE_KEY="${OCR_KEY}" \
O2J_DB_PATH=work/o2j.db \
uv run --extra serve uvicorn backend.main:app --host 127.0.0.1 --port 8000
