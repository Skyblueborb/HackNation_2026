#!/usr/bin/env bash
# Uruchom cały lokalny stos: llama-server (LLM) + FastAPI + Vite.
# Bez GPU i bez OCR obrazowego -- tekst czytany jest z warstwy tekstowej PDF-a.
#
#   bash scripts/dev-up.sh              # LLM + backend + frontend
#   bash scripts/dev-up.sh --no-llm     # bez LLM (/api/analyze zwróci sam tekst)
#   bash scripts/dev-up.sh --no-web     # bez frontendu (samo API na :8000)
#   API_TOKEN=<token> bash scripts/dev-up.sh --lan  # API dostępne w LAN (:8000)
#
# Domyślnie API słucha tylko na 127.0.0.1. --lan wymaga API_TOKEN.
# Ctrl-C zatrzymuje wszystko, co ten skrypt wystartował.

set -euo pipefail
cd "$(dirname "$0")/.."

WITH_LLM=1
WITH_WEB=1
LAN=0
for arg in "$@"; do
  case "$arg" in
    --no-llm) WITH_LLM=0 ;;
    --no-web) WITH_WEB=0 ;;
    --lan) LAN=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "nieznany argument: $arg" >&2; exit 2 ;;
  esac
done

# .env jest opcjonalny; .env.example opisuje każdą zmienną.
if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi

: "${API_KEY:=dev-key}"
: "${WEB_OCR_BACKEND:=text}"
: "${OCR_LLM_MODEL:=local-llm}"
: "${O2J_DB_PATH:=work/o2j.db}"
: "${CORS_ORIGINS:=http://localhost:3000}"
export API_KEY WEB_OCR_BACKEND OCR_LLM_MODEL O2J_DB_PATH CORS_ORIGINS
export API_TOKEN="${API_TOKEN:-}"
if [[ "$LAN" == "1" ]]; then
  [[ -n "$API_TOKEN" ]] || { echo "--lan wymaga API_TOKEN (ustaw w .env)" >&2; exit 2; }
  export O2J_DEV_NO_AUTH=0
  API_HOST=0.0.0.0
else
  # Lokalny stos działa bez tokenu, ale backend wymaga jawnej zgody na brak auth.
  export O2J_DEV_NO_AUTH="${O2J_DEV_NO_AUTH:-1}"
  API_HOST=127.0.0.1
fi
export PYTHONPATH="src:."

if [[ "$WITH_LLM" == "1" ]]; then
  export OCR_LLM_PROCESSOR="${OCR_LLM_PROCESSOR:-ocr_api.llm_processor:processor}"
else
  export OCR_LLM_PROCESSOR=""
fi

PIDS=()
cleanup() {
  echo
  echo "[dev-up] zatrzymuję ..."
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Czekaj, aż URL odpowie; kod HTTP nie ma znaczenia (401 też znaczy "żyje").
wait_for() {
  local url="$1" name="$2" tries="${3:-60}"
  for ((i = 0; i < tries; i++)); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null || [[ $? == 22 ]]; then
      echo "[dev-up] $name gotowy"
      return 0
    fi
    sleep 2
  done
  echo "[dev-up] $name nie odpowiedział po $((tries * 2))s" >&2
  return 1
}

mkdir -p work

if [[ "$WITH_LLM" == "1" ]]; then
  PORT="$(uv run python -c "
from lab.llm.config import load_models
from lab.paths import REPO_ROOT
print(load_models(REPO_ROOT / 'configs' / 'models.yaml')['${OCR_LLM_MODEL}'].port)
")"
  echo "[dev-up] llama-server: profil ${OCR_LLM_MODEL}, port ${PORT}"
  echo "[dev-up] pierwszy raz? model się ściąga, to może potrwać kilka minut"
  uv run lab serve --model "$OCR_LLM_MODEL" &
  PIDS+=($!)
  wait_for "http://localhost:${PORT}/health" "llama-server (${OCR_LLM_MODEL})" 300
else
  echo "[dev-up] LLM wyłączony -- /api/analyze zwróci sam tekst dokumentu"
fi

echo "[dev-up] backend: http://${API_HOST}:8000  (baza: ${O2J_DB_PATH})"
# Domyślnie 127.0.0.1; --lan wymaga API_TOKEN i wiąże 0.0.0.0.
uv run --extra serve uvicorn backend.main:app --host "$API_HOST" --port 8000 &
PIDS+=($!)
wait_for "http://localhost:8000/api/health" "backend" 60

if [[ "$WITH_WEB" == "1" ]]; then
  if [[ ! -d frontend/node_modules ]]; then
    echo "[dev-up] instaluję zależności frontendu ..."
    (cd frontend && npm install)
  fi
  echo "[dev-up] frontend: http://localhost:3000"
  (cd frontend && npm run dev) &
  PIDS+=($!)
fi

echo
echo "[dev-up] gotowe. Ctrl-C kończy."
wait
