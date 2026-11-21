# Backend API i baza danych

## Jak uruchomić

**Lokalnie (dev):**
```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=src:. O2J_DB_PATH=work/o2j.db .venv/bin/uvicorn backend.main:app --port 8000
```

**Docker (docelowo, baza po stronie serwera):**
```bash
docker compose up --build
```
Plik `.db` żyje w named volume `o2j-data` pod `/data/o2j.db` — nie w repo.
Skopiuj `.env.example` do `.env` i ustaw `API_TOKEN`, aby zabezpieczyć API.

Frontend: `cd frontend && npm run dev` (port 3000, proxy `/api` → 8000).

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
