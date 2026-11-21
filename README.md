# o2j-lab — Odwołania2json

Lab badawczy pod konkurs UZP **"Odwołania2json"** (Krajowa Izba Odwoławcza /
zamówienia publiczne): zadanie konkursowe to zamiana PDF-ów sprawy odwoławczej
(odwołanie, pełnomocnictwo, potwierdzenie przelewu) na ustrukturyzowany JSON,
oceniane metryką F1 + elastyczność. Ten lab to **rama pomiarowa** budowana
jako pierwsza — ewaluator, podział dev/holdout, cache, normalizatory — żeby
porównania modeli LLM i wariantów OCR były wiarygodne, a nie oparte na "wygląda
lepiej". Pełny research rationale: `AI/PLAN.md` (oryginalny plan) oraz plik
planu wykonawczego z korektami, patrz sekcja *Dokumentacja* na końcu.

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
tests/          179 testów pytest pokrywających normalizatory, spec klas,
                ewaluator, split, cache, manifest, OCR smoke.
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

- Dane konkursowe (180 plików PDF+JSON w `dane/przyklad_NN/`) żyją w
  **osobnym repo** organizatora, poza tym repozytorium. Ścieżkę do nich
  wskazuje `configs/paths.yaml` (`data_root`), domyślnie:

```yaml
data_root: /Users/kacperwrobel/Documents/hackaton/dane/hacknation-2026
work_root: work
```

  Można ją nadpisać zmienną środowiskową `O2J_DATA_ROOT` albo flagą
  `--data-root` większości komend CLI.

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
| `ocr-smoke` | Minimalny sanity-check OCR: jeden silnik (tesseract `pol`), jeden poziom szumu (`light`), kilka stron. **To nie jest pełny benchmark silnik×szum z PLAN.md §8A** — to świadomie okrojony dymny test. |
| `ocr-prepare` | *(stub, `NotImplementedError`)* Przygotowanie wejść do porównania OCR. |
| `ocr-run` | *(stub, `NotImplementedError`)* Uruchomienie silnika OCR na przygotowanych wejściach. |
| `ocr-eval` | *(stub, `NotImplementedError`)* Ewaluacja wyjścia OCR (CER/WER) względem wzorca. |
| `collect` | *(stub, `NotImplementedError`)* Zbieranie wyników z wielu runów. |
| `plots` | *(stub, `NotImplementedError`)* Generowanie wykresów z zebranych wyników. |
| `report` | *(stub, `NotImplementedError`)* Generowanie raportu finalnego. |

Przykład bramy Fazy A (identity gate — predykcje = gold, musi dać F1 = 1.0):

```bash
uv run lab split --holdout 20 --seed 42
uv run lab ingest --extractor pdfplumber
uv run lab eval --run work/runs/_identity
uv run lab board
```

## Status: co jest zrobione, co nie

**Zrobione (Faza A — rdzeń pomiaru, kompletna):**
- Specyfikacja 3 klas dokumentów jako YAML + dwa niezależne emitery
  (`build_model` → Pydantic v2 do walidacji, `build_json_schema` → ręczny
  JSON Schema bez `$ref`/`$defs` do gramatyki llama.cpp).
- Normalizatory (daty PL, kwoty, NIP/REGON/KRS/NRB, numery BZP/TED) —
  zweryfikowane jako idempotentne na wszystkich 180 plikach gold.
- Ewaluator: flatten/match/compare/metrics z trzema politykami null
  (skip/tp/strict), exact i fuzzy, greedy alignment list.
- `lab split` — stratyfikowany podział dev/holdout po zestawach.
- Cache adresowany treścią (sha256 PDF) + `lab ingest`.
- Manifest runów i `lab board`.

**Zrobione jako okrojona wersja (Faza B — mini, NIE pełny benchmark):**
- `lab ocr-smoke` — dymny test jednego silnika (tesseract `pol`) na jednym
  poziomie szumu. Pełna siatka silnik × poziom szumu z `AI/PLAN.md` §8A
  (`ocr-prepare`/`ocr-run`/`ocr-eval` na pełnej konfiguracji, wiele silników,
  4 poziomy degradacji) **nie została zbudowana** — to świadoma decyzja, nie
  pominięcie.
- Lokalne serwowanie modeli LLM przez llama.cpp skonfigurowane do ręcznego
  testowania (patrz niżej), ale **nie zintegrowane** z pipeline'em.

**NIE zrobione:**
- Brak automatycznej ekstrakcji LLM → JSON (nie istnieje `lab run` / `lab
  extract`). Modele są obecnie testowane tylko ręcznie.
- Brak produkcyjnej aplikacji `o2j` (CLI z `input/`/`output/`, kontrakt z
  regulaminu konkursu) — tylko `src/o2jcore` jako rdzeń, który ta aplikacja
  będzie mogła wykorzystać.
- Brak pełnego silnika/benchmarku OCR i siatki poziomów szumu — tylko
  smoke test.

179/179 testów pytest przechodzi (`uv run pytest -q`).

## Jak ręcznie przetestować lokalne modele LLM

`configs/models.yaml` definiuje 3 modele, każdy na swoim porcie (jeden
`llama-server` = jeden proces = jeden port):

| Model | Port | HF repo |
|---|---|---|
| `qwen3-4b` | 8081 | `Qwen/Qwen3-4B-GGUF:Q4_K_M` |
| `qwen3-8b` | 8082 | `Qwen/Qwen3-8B-GGUF:Q4_K_M` |
| `bielik-11b` | 8083 | `speakleash/Bielik-11B-v3.1-Instruct-GGUF:Q4_K_M` |

### 1. Sprawdź, czy serwer już działa

```bash
curl http://localhost:8081/health
```

Odpowiedź `{"status":"ok"}` (lub podobna) oznacza, że serwer już stoi —
nie trzeba go startować.

### 2. Jeśli nie działa — odpal go

```bash
llama-server -hf Qwen/Qwen3-4B-GGUF:Q4_K_M --port 8081 -c 8192 -ngl 99 --jinja
```

Analogicznie dla pozostałych (zmień `-hf` i `--port` zgodnie z tabelą
powyżej). `--jinja` jest wymagane, żeby użyć szablonu czatu z pliku GGUF.
`-ngl 99` offloaduje wszystkie warstwy na GPU/Metal (na czysty CPU: `-ngl 0`).
Przy ograniczeniach dysku/RAM trzymaj naraz tylko jeden model.

### 3. Wyślij testowe zapytanie (OpenAI-compatible)

```bash
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-4b","messages":[{"role":"user","content":"Powiedz jedno zdanie po polsku."}],"temperature":0}'
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
BF16 `lightonai/LightOnOCR-3-4B`, preloaded at startup. Local MLX is a separate
app used only for testing on the Mac. The two dependency sets never mix.

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

OCR runs in grounding mode by default (`OCR_PROMPT=grounding`). Output is
markdown with headings, tables, lists and block labels with bounding boxes, e.g.
`![title](80,70,920,140)` followed by `# Nagłówek`. Set `OCR_PROMPT=""` for
plain transcription markdown without bounding boxes. Grounding adds about 25%
more output tokens.

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
  OCR_PROMPT=grounding \
  API_KEY=<local-test-key> \
  uv run --extra local --extra serve \
  local-ai serve --host 0.0.0.0 --port 8001 --verbose
```

`/health` reports the 0.8B id. Omit the env vars next run to return to 4B.

The grounding prompt string is exactly `grounding`; it produces markdown with
headings plus `![label](x1,y1,x2,y2)` block boxes. Use `OCR_PROMPT=""` for plain
markdown without boxes.

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
API_KEY=dev-key WEB_OCR_BACKEND=mlx \
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
API_KEY=<key> OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
  OCR_LLM_MODEL=qwen3-8b-l4 \
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Local LLM mode (separate, like `local-ai` for OCR): `local-llm serve`
(Metal) or `local-llm serve --cpu`. See `docs/llm-runtime.md`.
Backend storage details: `docs/BACKEND.md`.
