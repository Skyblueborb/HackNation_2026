# o2j-lab — Odwołania2json

Lab badawczy pod konkurs UZP **"Odwołania2json"** (Krajowa Izba Odwoławcza /
zamówienia publiczne): zadanie konkursowe to zamiana PDF-ów sprawy odwoławczej
(odwołanie, pełnomocnictwo, potwierdzenie przelewu) na ustrukturyzowany JSON,
oceniane metryką F1 + elastyczność. Ten lab to **rama pomiarowa** budowana
jako pierwsza — ewaluator, podział dev/holdout, cache, normalizatory — żeby
porównania modeli LLM i wariantów OCR były wiarygodne, a nie oparte na "wygląda
lepiej". Pełny research rationale: `AI/PLAN.md` (oryginalny plan) oraz plik
planu wykonawczego z korektami, patrz sekcja *Dokumentacja* na końcu.
Komendy CLI, modele i zmierzona wydajność: `docs/CLI.md`.

## Struktura projektu

```
src/o2jcore/    rdzeń współdzielony z przyszłą aplikacją produkcyjną o2j
                (bez zależności lab-only): spec klas dokumentów (YAML -> Pydantic
                + JSON Schema), normalizatory wartości/dat/sum kontrolnych,
                ekstrakcja tekstu z PDF, smoke-test OCR.
src/lab/        kod samego laboratorium: CLI, cache, split dev/holdout,
                ewaluator (flatten/match/compare/metrics/errors), manifest
                runów, leaderboard, oraz `lab/llm/` (istniejący pipeline
                OCR-tekst -> LLM -> JSON).
src/ocr_common/ kontrakty i współdzielony pipeline OCR (ports, pipeline, registry).
src/ocr_api/    produkcyjny serwer HTTP na GPU (CUDA BF16) + adapter do `lab/llm`.
src/local_ai/   osobny serwer MLX tylko do testów lokalnych na Macu
                oraz `local-llm` (lokalny tryb LLM).
backend/        serwer FastAPI + SQLite dla frontendu; endpoint `/api/analyze`
                łączy OCR, LLM i bazę danych.
frontend/       aplikacja React/Vite (ZIP -> OCR/LLM -> formularze -> SQLite).
configs/        konfiguracja jako dane: klasy dokumentów (classes/*.yaml),
                enum czynności (enums/), modele LLM (models.yaml), ścieżki
                (paths.yaml).
work/           artefakty uruchomień: cache, splits.json, runs/, raporty —
                CAŁOŚĆ gitignored, nic z tego nie jest w repo.
tests/          300 testów pytest; część wymaga danych konkursowych
                (`O2J_DATA_ROOT`), bez nich testy danych kończą się błędem.
AI/PLAN.md      oryginalny plan badawczy (po polsku).
```

Zasada architektoniczna: **każda klasa dokumentu to plik YAML, nie kod
Pythona**. Dodanie czwartej klasy dokumentu = nowy plik w `configs/classes/`,
zero zmian w `src/`. To wprost punktowane w regulaminie konkursu (do 20 pkt za
elastyczność bez zmian w kodzie).

## Setup

- Python **3.13** (pinowane w `.python-version`, wymagane przez regulamin).
- Instalacja zależności:

```bash
uv sync --extra lab
```

`uv.lock` jest źródłem prawdy dla zależności. Root `requirements.txt` nie jest
utrzymywany (`backend/requirements.txt` to osobny plik dla obrazu backendu).

- Dane konkursowe (180 plików PDF+JSON w `dane/przyklad_NN/`) żyją w
  **osobnym repo** organizatora, poza tym repozytorium. `data_root`
  w `configs/paths.yaml` to katalog **nad** `dane/` (root repo z danymi),
  nie sam katalog `dane/`:

```yaml
data_root: /absolute/path/to/hacknation-2026-data
work_root: work
```

  Nadpisz ją zmienną `O2J_DATA_ROOT` albo flagą `--data-root` wybranych
  komend CLI. `$REPO_ROOT` w tym dokumencie oznacza root tego repo
  (`git rev-parse --show-toplevel`), nie stałą ścieżkę na dysku.

## Komendy `lab`

```bash
uv run lab --help
```

| Komenda | Co robi |
|---|---|
| `split` | Dzieli dane na dev/holdout (stratyfikowane, z seedem, po zestawach, nie po plikach). |
| `ingest` | Ekstrahuje tekst/layout z PDF-ów do cache adresowanego treścią (sha256). |
| `eval` | Ewaluuje predykcje względem gold JSON (micro-F1 exact/fuzzy, trzy polityki null: skip/tp/strict). |
| `board` | Odświeża i wypisuje leaderboard ze wszystkich runów pod `<work_root>/runs/`. |
| `ocr-smoke` | Minimalny sanity-check OCR: jeden silnik (tesseract `pol`), jeden poziom szumu (`light`), kilka stron. Nie jest to pełna siatka silnik × szum z `AI/PLAN.md` §8A. |
| `models-check`, `predict-one`, `run`, `sweep` | Projekt LLM: health, predykcja jednego dokumentu, runy i sweepy z F1. |

Pełny flow PDF → OCR → LLM → JSON i tryb zdalny opisuje `docs/CLI.md`.

Przykład bramy Fazy A (identity gate — predykcje = gold, musi dać F1 = 1.0):

```bash
uv run lab split --holdout 20 --seed 42
uv run lab ingest --extractor pdfplumber
uv run lab eval --run work/runs/_identity
uv run lab board
```

## Status

- Rdzeń pomiaru: specyfikacje 3 klas jako YAML, normalizatory, ewaluator
  (exact/fuzzy, polityki null), `lab split`, cache sha256, manifest i `board`.
- Pipeline LLM zintegrowany: `lab predict-one`, `lab run`,
  `ocr-pdf2json` oraz opcjonalny `llm` w odpowiedzi `/api/analyze`.
  Profile modeli i porty: `configs/models.yaml`.
- OCR: `ocr-api` (CUDA) i `local-ai` (MLX) udostępniają `/analyze`;
  backend ma też ścieżkę tekstową `WEB_OCR_BACKEND=text` bez GPU i wag.
- Pełny demo stack: frontend React/Vite + FastAPI + SQLite (`docs/BACKEND.md`).
- `lab ocr-smoke` to dymny test jednego silnika, nie pełna siatka
  silnik × szum z `AI/PLAN.md` §8A. Komendy `ocr-prepare`, `ocr-run`,
  `ocr-eval`, `collect`, `plots`, `report` są obecnie stubami.

`uv run pytest -q` zbiera 300 testów. Testy zależne od danych konkursowych
wymagają ustawionego `O2J_DATA_ROOT`; bez nich kończą się błędem.

## Jak ręcznie przetestować lokalne modele LLM

Profile modeli, porty, repozytoria HF i flagi serwera są w
`configs/models.yaml` — to jedyne źródło tych wartości. Jeden
`llama-server` to jeden proces i jeden port; trzymaj naraz jeden model.
Szczegóły: `docs/llm-runtime.md`.

### 1. Sprawdź, czy serwer już działa

Podstaw `<port>` wartością z `configs/models.yaml`:

```bash
curl http://localhost:<port>/health
```

Odpowiedź `{"status":"ok"}` (lub podobna) oznacza, że serwer już stoi.

### 2. Jeśli nie działa — odpal go

```bash
uv run lab serve --model <profil>     # <profil> = klucz z configs/models.yaml
```

`--jinja` w flagach profilu jest wymagane dla szablonu czatu z GGUF.
`-ngl 99` offloaduje wszystkie warstwy na GPU/Metal (CPU: `-ngl 0`).

### 3. Wyślij testowe zapytanie (OpenAI-compatible)

```bash
curl http://localhost:<port>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<profil>","messages":[{"role":"user","content":"Powiedz jedno zdanie po polsku."}],"temperature":0}'
```

Qwen3 domyślnie generuje tryb "myślenia" — dla structured output dopisz
`/no_think` na końcu wiadomości użytkownika (patrz `no_think_suffix` w
`configs/models.yaml`).

## Licencje

Każdy komponent — kod i wagi modeli — jest wpisany do `docs/LICENSES.md` w
chwili dodania, z datą weryfikacji. Zasada: wyłącznie open source (MIT,
Apache-2.0, BSD, MPL dla kodu; Apache-2.0/MIT dla wag modeli); PyMuPDF (AGPL)
jest zakazane.

## Dokumentacja

- `docs/MODEL_CHECK.md` — jak uruchamiać `lab model-check`, czytać raporty i
  diagnozować, czy problem leży w OCR czy w LLM.
- `AI/PLAN.md` — oryginalny plan badawczy (silniki OCR, modele, warianty
  pipeline'u, metryki F1).
- Plan wykonawczy z korektami do `AI/PLAN.md` (zweryfikowane fakty o danych,
  regulaminie i środowisku — 60 zestawów nie 39, 16 GB RAM nie 24 GB,
  priorytet małych modeli, Faza B okrojona) — trzymany poza repo w notatkach
  sesji Claude.


## OCR API

An optional LLM module can be plugged in with `OCR_LLM_PROCESSOR=module:attr`;
the core contains no LLM code. The lab LLM pipeline is already bridged through
`ocr_api.llm_processor`; enable it with
`OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor` and
`OCR_LLM_MODEL=qwen3-8b` (a key in `configs/models.yaml`). Start that LLM server
with `lab serve --model qwen3-8b`. Then `/analyze` gains an `llm` field with
`class`, `data`, `error`, `llm_calls`. See `docs/llm-module-contract.md`.

Production runs on an NVIDIA L4 (Ubuntu Noble) box with PyTorch CUDA, full
BF16 `lightonai/LightOnOCR-3-0.8B`, preloaded at startup. Local MLX is a separate
app used only for testing on the Mac. The two dependency sets never mix.

Two credentials, easy to confuse: the standalone OCR services (`ocr-api`,
`local-ai`) use `API_KEY` with the `X-API-Key` header. The FastAPI backend
(`backend.main`) uses `API_TOKEN` with `X-API-Token` or `Bearer`. The backend
does not need `API_KEY` for the `text` OCR path.

### 1. Generate an API key

```bash
uv sync --extra serve
uv run ocr-api keygen
```

That prints one 256-bit key, e.g. `xY3...`. Keep it secret. Store it on the
server as `API_KEY`; give it to judges with the URL.

The app refuses to start without `API_KEY`.

### 2. Run the GPU service

```bash
docker build -f Dockerfile.gpu -t ocr-gpu .
docker run --rm --gpus all -p 8000:8000 \
  -e API_KEY=<generated-key> \
  ocr-gpu
```

Or without Docker, on the L4 box:

```bash
uv sync --extra gpu --extra serve
API_KEY=<generated-key> ocr-api serve --host 0.0.0.0 --port 8000
```

Defaults: host `0.0.0.0`, port `8000`. Override with `OCR_HOST`/`OCR_PORT` or
the CLI flags. Add `--verbose` to either `serve` command for DEBUG console logs;
`OCR_VERBOSE=1` does the same. Logs show model load time, page size, blank-page
checks, OCR time and character count, and total request time. API keys are never
logged. Verify with:

```bash
curl http://<public-ip>:8000/health
```

Open port 8000 in the cloud security group. For a public HTTPS link without
opening inbound ports:

```bash
cloudflared tunnel --url http://localhost:8000
```

Give judges the `https://*.trycloudflare.com` URL plus `X-API-Key`.

### 3. Analyze a scanned PDF

```bash
curl -H 'X-API-Key: <generated-key>' \
  -F 'file=@scan.pdf' \
  http://<public-ip>:8000/analyze
```

Response: `{"backend": "cuda", "pages": [{"page": 1, "text": "..."}]}`.

OCR runs full-page transcription by default (`OCR_PROMPT=""`). Output is plain
markdown with headings, tables and lists. Grounding is opt-in with
`OCR_PROMPT=grounding`: it adds bounding-box labels such as
`![title](80,70,920,140)` but does not reliably transcribe long documents, so
do not use it for PDF-to-JSON extraction.

Speed knobs: `OCR_MAX_EDGE` (default `2048`) caps page pixels;
`OCR_MAX_TOKENS` (default `2048`) caps output length. `OCR_ATTN_IMPL` defaults
to `sdpa`, which is fast on L4 without extra packages. `OCR_PRELOAD=0` disables
startup preload.

### Local testing on the Mac (separate app)

```bash
bash scripts/make-mlx-model.sh
uv sync --extra local --extra serve
API_KEY=<local-test-key> \
  MLX_MODEL=models/LightOnOCR-3-4B-mlx-8bit \
  uv run --extra local --extra serve \
  local-ai serve --host 0.0.0.0 --port 8000
```

Same `/analyze` and `/health` contract; response `backend` is `mlx`.

### One-time 0.8B trial

Default stays the 4B 8-bit model. To try the smaller model once:

```bash
bash scripts/make-mlx-model-08b.sh
OCR_MODEL=fwgpiyawudk/LightOnOCR-3-0.8B-MLX-8bit \
  MLX_MODEL=models/LightOnOCR-3-0.8B-mlx-8bit \
  API_KEY=<local-test-key> \
  uv run --extra local --extra serve \
  local-ai serve --host 0.0.0.0 --port 8001 --verbose
```

`/health` reports the 0.8B id. Omit the env vars next run to return to 4B.

Both MLX models use the same empty-prompt transcription default. Set
`OCR_PROMPT=grounding` only when bounding boxes are needed.

Keep the Mac awake during judging:

```bash
caffeinate -dims
```

## Full demo: frontend + SQLite backend + OCR/LLM

The React app talks to the FastAPI backend on port 8000 through Vite's `/api`
proxy. The backend stores results in SQLite and runs OCR + optional LLM.

```bash
# Backend (local Mac: MLX OCR, no LLM server needed)
uv sync --extra serve --extra local
API_TOKEN=dev-key WEB_OCR_BACKEND=mlx \
  MLX_MODEL=models/LightOnOCR-3-4B-mlx-8bit \
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1

# Frontend
cd frontend && npm install && npm run dev
```

Open `http://localhost:3000`, upload a ZIP of scanned PDFs, click
**Przetwórz do JSON**. Each PDF is sent to `/api/analyze`, OCR/LLM output is
saved to SQLite, and the forms are hydrated from the stored canonical JSON.

Production on NVIDIA L4:

```bash
uv sync --extra gpu --extra serve
lab serve --model qwen3-8b-l4     # LLM: full GPU offload + flash attention
API_TOKEN=<token> OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
  OCR_LLM_MODEL=qwen3-8b-l4 \
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Local LLM mode (separate, like `local-ai` for OCR): `local-llm serve`
(Metal) or `local-llm serve --cpu`. See `docs/llm-runtime.md`.
Backend storage details: `docs/BACKEND.md`.
