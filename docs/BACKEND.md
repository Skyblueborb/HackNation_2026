# Backend API i baza danych

## Jak uruchomić

**Najszybciej — cały stos jednym poleceniem (bez GPU):**
```bash
cp .env.example .env          # opcjonalne; skrypt ma sensowne domyślne wartości
bash scripts/dev-up.sh        # llama-server + FastAPI :8000 + Vite :3000
bash scripts/dev-up.sh --no-llm   # bez LLM: /api/analyze zwróci sam tekst
API_TOKEN=<token> bash scripts/dev-up.sh --lan  # API w LAN na 0.0.0.0:8000
```
Domyślnie skrypt wiąże API z `127.0.0.1`; `--lan` wymaga `API_TOKEN`.
Ctrl-C zatrzymuje wszystko, co skrypt wystartował.

**Ręcznie (samo API):**
```bash
uv sync --extra serve
API_TOKEN=dev-key WEB_OCR_BACKEND=text O2J_DB_PATH=work/o2j.db \
  PYTHONPATH=src:. uv run --extra serve uvicorn backend.main:app --port 8000
```

**Docker (baza po stronie serwera):**
```bash
cp .env.example .env          # ustaw API_TOKEN; API_KEY tylko dla serwisów OCR
docker compose up --build     # API :8000, frontend :3000
```
Plik `.db` żyje w named volume `o2j-data` pod `/data/o2j.db` — nie w repo
i nie w obrazie.

Frontend osobno (dev): `cd frontend && npm install && npm run dev`
(port 3000, proxy `/api` → 8000).

### Frontend lokalnie, OCR + LLM na L4 — bez tunelu SSH

Backend i LLM działają na L4. Frontend działa na Macu i przez `O2J_API_TARGET`
celuje bezpośrednio w backend na L4. Port LLM (`8082`) zostaje prywatny —
backend wywołuje go przez `localhost` na tej samej maszynie.

**Na L4:**

```bash
# 1. LLM — tylko localhost:8082, nie wystawiaj publicznie
uv run lab serve --model qwen3-8b-l4

# 2. Backend — 0.0.0.0:8000, z API_TOKEN
API_TOKEN=<token> \
WEB_OCR_BACKEND=cuda \
OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
OCR_LLM_MODEL=qwen3-8b-l4 \
CORS_ORIGINS=http://localhost:3000 \
uv run --extra gpu --extra serve uvicorn backend.main:app \
  --host 0.0.0.0 --port 8000
```

W cloud security group otwórz tylko `8000`. `8082` zostaje zamknięty.

**Na Macu:**

```bash
cd frontend
O2J_API_TARGET=http://<L4-IP>:8000 \
O2J_API_TOKEN=<token> \
npm run dev
```

Vite proxy wysyła `/api` na `http://<L4-IP>:8000` i dodaje `X-API-Token`.
Zmienne są czytane przez proces Node, nie trafiają do bundle'a JS.

CLI z tego samego ustawienia:

```bash
uv run ocr-pdf2json plik.pdf \
  --remote http://<L4-IP>:8000 \
  --api-token <token> \
  --save-ocr \
  --out-dir output
```

### Backend lokalnie na Macu, OCR + LLM na L4

Backend może zostać na Macu i przekazać cały plik do zdalnego serwisu
`ocr-api`. Serwis na L4 robi OCR i LLM, więc lokalny proces nie ładuje wag
i nie potrzebuje LLM servera.

**Na L4** — postępuj według `docs/gpu-server/README.md`, w tym LLM na
`localhost:8082`, a `ocr-api serve` z `OCR_LLM_PROCESSOR` i
`OCR_LLM_MODEL=qwen3-8b-l4`. Wystaw tylko port `8000` z `API_KEY`.

**Na Macu:**

```bash
API_TOKEN=<token> \
WEB_OCR_BACKEND=remote \
OCR_SERVICE_URL=http://<L4-IP>:8000 \
OCR_SERVICE_KEY=<API_KEY> \
O2J_DB_PATH=work/o2j.db \
uv run --extra serve uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Zostaw `OCR_LLM_PROCESSOR` puste — LLM jest już po stronie L4. Backend
przesyła PDF do `POST <OCR_SERVICE_URL>/analyze` z nagłówkiem `X-API-Key`
i przekazuje zwrócone `pages` oraz `llm` do swojego `SQLite`/API.

Frontend zostaje domyślny (`O2J_API_TARGET` nie jest potrzebny), bo backend
jest lokalny:

```bash
cd frontend && npm run dev
```

`OCR_REMOTE_TIMEOUT` (domyślnie `900` s) kontroluje timeout żądania.

Cały lokalny stos — backend + frontend — uruchamia jednym poleceniem
`scripts/connect-gpu.sh`. Przyjmuje osobno klucz serwisu OCR i token backendu:

```bash
bash scripts/connect-gpu.sh <L4-IP>:8000 <OCR_API_KEY> <BACKEND_API_TOKEN>
```

Jeśli trzeci argument zostanie pominięty, skrypt wygeneruje token backendu
i wypisze go na ekranie. Skrypt ustawia `O2J_API_TOKEN` dla Vite, więc frontend
od razu wysyła poprawny `X-API-Token`. Domyślnie backend i frontend działają
w odłączonej sesji tmux `o2j-connect` — skrypt wypisuje komendy `attach` i
`stop`. Dodaj `--no-tmux`, żeby procesy były dziećmi terminala i zatrzymywały
się przez Ctrl-C.

## Zmienne środowiskowe

Wszystkie opisane są w `.env.example`. Dwie łatwo pomylić:

* **`API_TOKEN`** — chroni *ten* backend (`X-API-Token` albo `Bearer`).
  Backend nie wystartuje bez tokenu, chyba że `O2J_DEV_NO_AUTH=1` (tylko lokalny dev).
* **`API_KEY`** — wymagany tylko przez samodzielne usługi OCR
  (`ocr-api serve`, `local-ai serve`). Backend nie potrzebuje go; klucz jest
  rozwiązywany leniwie przy żądaniach chronionych przez `verify_key`.

Pozostałe zmienne: `O2J_MAX_UPLOAD_MB` (domyślnie 25) ogranicza rozmiar PDF-a,
`OCR_MAX_UPLOAD_BYTES` (domyślnie 50 MB) w usługach OCR,
`OCR_LLM_CONCURRENCY` (domyślnie 1) steruje limitem wywołań LLM,
`OCR_LLM_GROUND_NULL=1` włącza sprawdzanie wartości w tekście,
`OCR_LLM_HEALTH_TIMEOUT` i `OCR_REMOTE_TIMEOUT` (domyślnie 900 s) dotyczą CLI.

`CORS_ORIGINS` nie może być puste. Puste wartości mają teraz bezpieczną
domyślną wartość `http://localhost:3000`; wildcard `*` wyłącza credentials.

## Skąd brany jest tekst dokumentu

`WEB_OCR_BACKEND` wybiera źródło tekstu:

| wartość | co robi | zależności |
|---|---|---|
| `text` | czyta warstwę tekstową PDF-a (`pdfplumber`) — bez GPU i bez wag modelu | `backend/requirements.txt` |
| `cuda` | OCR obrazowy na NVIDII (`ocr_api.backends.CudaBackend`) | extra `gpu` (`torch`, `transformers`) |
| `mlx` | OCR obrazowy na Macu/Metal (`local_ai.app.MlxBackend`) | extra `local` (`mlx-vlm`) + wagi MLX |

Wszystkie 180 dokumentów konkursowych ma warstwę tekstową, a docelowy runtime
to laptop biurowy bez GPU — dlatego `text` jest właściwą ścieżką lokalnie
i domyślną w `docker-compose.yml`. OCR obrazowy jest potrzebny tylko dla
prawdziwych skanów; bramkę „czy trzeba OCR" daje
`o2jcore.text.pdf_text.has_text_layer()`.

Opcjonalny LLM ładuje `OCR_LLM_PROCESSOR=module.path:attribute` przez
`ocr_common.load_llm_processor`; gdy go nie ma, `canonical_json` to
`{"raw_text": ...}`. Profil modelu wybiera `OCR_LLM_MODEL`
(klucz w `configs/models.yaml`) — serwer tego profilu musi już działać,
patrz `docs/llm-runtime.md`.

## Cztery magazyny JSON

| Tabela | Zawartość |
|---|---|
| `json_odwolanie` | kanoniczny JSON odwołania + provenance |
| `json_pelnomocnictwo` | kanoniczny JSON pełnomocnictwa + provenance |
| `json_przelew` | kanoniczny JSON przelewu + provenance |
| `correction_sessions` + `correction_items` | źle odczytany JSON, poprawiony JSON i różnice per pole |

**Jeden plik z ZIP-a = jeden dokument (`client_doc_id`).** W jednej sprawie może
być np. 3 przelewy, 2 odwołania i 0 pełnomocnictw — każdy zapisuje się jako
osobny byt, nie jako poprawka poprzedniego. Unikalny indeks w `source_documents`
idzie po `client_doc_id`, nie po samej klasie dokumentu.

Wynik modelu w magazynach 1–3 **nie jest nadpisywany**. Poprawki z UI trafiają
tylko do magazynu 4 jako pary `predicted_json → corrected_json`, dzięki czemu:

* można dalej mierzyć czyste F1 predykcji,
* powstają pary treningowe do douczania modelu (dynamiczny few-shot / LoRA).

Pola `validator_ok` i `grounded_ok` w `correction_items` odsiewają poprawki,
które nie przeszły sumy kontrolnej albo nie występują w tekście źródłowym.

## Endpointy

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/api/health` | status (bez tokenu, do healthchecku) |
| POST | `/api/analyze` | multipart PDF + `client_token` + `doc_class`: OCR, opcjonalny LLM, zapis wyniku; zwraca `pages`, `llm` (gdy skonfigurowany) i `canonical_json` |
| POST | `/api/documents/ingest` | zapis wyniku lub poprawki |
| GET | `/api/documents` | lista wyników (filtry: `client_token`, `doc_class`, `job_id`) |
| GET | `/api/documents/{id}` | jeden wynik (JSON + provenance + liczba poprawek) |
| PATCH | `/api/documents/{id}/corrections` | dopisanie poprawek per pole |
| GET | `/api/jobs/{id}` | status zadania |

Nie ma endpointu zwracającego surowy tekst dokumentu ani gold JSON.

## Eksport danych treningowych (tylko CLI)

```bash
PYTHONPATH=src:. O2J_DB_PATH=work/o2j.db \
  .venv/bin/python -m backend.export_training --class odwolanie --out work/pary.jsonl
```

Domyślnie eksportuje tylko „czyste" sesje. Flaga `--include-unverified` dodaje
również poprawki, które nie przeszły walidacji.

## Bezpieczeństwo — ważna uwaga

Baza i dane są po stronie serwera, ale jeśli jury ma pełny dostęp do hosta,
na którym odpala `docker compose`, technicznie może odczytać pliki z volume.
Gwarancja jest więc **organizacyjna**: w repozytorium i w obrazie Dockera nie ma
żadnych prawdziwych dokumentów ani gold JSON — dane są montowane w runtime
przez `O2J_DATA_ROOT`. Token API (`API_TOKEN`) chroni przed nieautoryzowanym
dostępem do HTTP, ale nie przed dostępem do samego hosta.

## Testy

```bash
PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_backend_db.py -q
```

## Znane ograniczenie frontendu

Formularz w `App.tsx` trzyma po jednym `Odwolujacy`/`Zamawiajacy`/`pelnomocnik`.
Przy wczytywaniu z bazy (`Wczytaj z bazy`) brany jest pierwszy element tablicy;
pozostałe są w JSON, ale nie są wyświetlane. Pełna obsługa list to osobny krok.
