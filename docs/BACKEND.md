# Backend API i baza danych

## Jak uruchomić

**Najszybciej — cały stos jednym poleceniem (bez GPU):**
```bash
cp .env.example .env          # opcjonalne; skrypt ma sensowne domyślne wartości
bash scripts/dev-up.sh        # llama-server + FastAPI :8000 + Vite :3000
bash scripts/dev-up.sh --no-llm   # bez LLM: /api/analyze zwróci sam tekst
```
Ctrl-C zatrzymuje wszystko, co skrypt wystartował.

**Ręcznie (samo API):**
```bash
uv sync --extra serve
API_KEY=dev-key WEB_OCR_BACKEND=text O2J_DB_PATH=work/o2j.db \
  PYTHONPATH=src:. uv run --extra serve uvicorn backend.main:app --port 8000
```

**Docker (baza po stronie serwera):**
```bash
cp .env.example .env          # ustaw API_TOKEN i API_KEY
docker compose up --build     # API :8000, frontend :3000
```
Plik `.db` żyje w named volume `o2j-data` pod `/data/o2j.db` — nie w repo
i nie w obrazie.

Frontend osobno (dev): `cd frontend && npm install && npm run dev`
(port 3000, proxy `/api` → 8000).

## Zmienne środowiskowe

Wszystkie opisane są w `.env.example`. Dwie łatwo pomylić:

* **`API_TOKEN`** — chroni *ten* backend (`X-API-Token` albo `Bearer`).
  Puste = brak autoryzacji, tylko do lokalnego dev-u.
* **`API_KEY`** — wymagany przez `ocr_common` (wspólny moduł usług OCR).
  Backend potrzebuje go, gdy wołane jest `/api/analyze`; bez niego ten
  endpoint zwraca 500 (`RuntimeError: API_KEY must be set`).

`CORS_ORIGINS` **nie może zostać puste** — puste włącza wildcard `*`.

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
