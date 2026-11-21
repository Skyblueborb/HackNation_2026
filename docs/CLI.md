# CLI — OCR, LLM i pomiar wydajności

Ten dokument opisuje narzędzia wiersza polecenia używane w projekcie: nowy
`ocr-pdf2json` (pełny flow PDF → OCR → LLM → JSON), badawczy CLI `lab` oraz
sposób pomiaru czasu i diagnozy błędów.

## 1. Szybki start

Ścieżki w tym dokumencie są przenośne. Ustaw je raz w powłoce:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
DATA_ROOT="/absolute/path/to/hacknation-2026-data"   # katalog NAD dane/
cd "$REPO_ROOT"
uv sync --extra local --extra serve --extra lab
```

`DATA_ROOT` to root osobnego repo z danymi konkursowymi; zawiera katalog
`dane/`. Można go też wskazać przez `configs/paths.yaml` lub `O2J_DATA_ROOT`.

Uruchom serwer LLM:

```bash
# terminal 1 — lokalny profil na Macu
uv run lab serve --model local-llm
# alternatywa CPU: uv run local-llm serve --cpu
```

Sprawdzenie:

```bash
curl http://localhost:8081/health    # {"status":"ok"}
```

Konwersja jednego PDF-a do JSON:

```bash
uv run ocr-pdf2json \
  "$DATA_ROOT/dane/przyklad_01/potwierdzenie_przelewu.pdf" \
  --out-dir output
```

Wynik: `output/potwierdzenie_przelewu.json`. Nazwa pliku jest taka sama jak
nazwa PDF-a (bez rozszerzenia). Domyślny katalog to `output/` — zapis obok
oryginału mógłby nadpisać gold JSON z danych konkursowych.

## 2. `ocr-pdf2json` — co robi

- sprawdza, czy serwer LLM dla wybranego profilu odpowiada na `/health`,
- sprawdza, czy wagi OCR istnieją lokalnie,
- raportuje stan backendu API (`:8000`), choć nie jest wymagany,
- renderuje strony PDF-a przez pypdfium2: 400 DPI, dłuższy bok 2048 px,
- wykonuje OCR z pustym promptem (`""`), czyli transkrypcję pełnej strony,
- przekazuje pełny dokument do wybranego procesora LLM,
- zapisuje kanoniczny JSON i wypisuje czasy: `render`, `ocr`, `llm`, `total`.

Opcje:

```text
pdf                  pojedynczy plik PDF
--out-dir KATALOG    gdzie zapisać JSON (domyślnie: output)
--ocr-model ŚCIEŻKA  lokalne wagi MLX (domyślnie 0.8B)
--llm-profile ID     klucz z configs/models.yaml (domyślnie local-llm)
--save-ocr           zapisz surowy tekst OCR do <basename>.ocr.txt
```

Flaga `--save-ocr` tworzy obok JSON-a plik `<basename>.ocr.txt` z sekcjami
`--- page N ---`. Tekst stron jest zapisywany dosłownie, także pusty — służy
do podglądu przy debugowaniu OCR. Działa też z `--remote`.

Przykład z 4B:

```bash
uv run ocr-pdf2json <pdf> \
  --ocr-model models/LightOnOCR-3-4B-mlx-8bit \
  --out-dir output
```

Jeśli LLM nie działa, skrypt kończy błędem z komunikatem zawierającym
`uv run lab serve --model <profil>`.

## 2b. Tryb zdalny (inna maszyna w LAN)

Jeśli modele działają na tym Macu, inna maszyna nie potrzebuje wag ani LLM.
Użyj `--remote` z adresem backendu:

```bash
uv run ocr-pdf2json przelew.pdf \
  --remote http://192.168.1.220:8000 \
  --out-dir output \
  --api-token <token>          # jeśli backend ma API_TOKEN
```

Tryb zdalny:
- nie sprawdza lokalnych wag ani lokalnego serwera LLM,
- wysyła PDF do `POST /api/analyze` z nagłówkiem `X-API-Token`,
- typ dokumentu wywnioskuje z tekstu (nazwa pliku tylko przy remisie);
  `--doc-class` nadpisuje wybór,
- zapisuje `<basename>.json` jak w trybie lokalnym,
- wypisuje czas całego żądania.

Backend musi nasłuchiwać na `0.0.0.0:8000` i być osiągalny z maszyny
klienckiej. Ustaw `API_TOKEN` na backendzie i przekaż ten sam token przez
`--api-token` albo `O2J_API_TOKEN`. Uwaga: `docker-compose.yml` wiąże port
`8000` z `127.0.0.1`, więc dla LAN użyj `uvicorn ... --host 0.0.0.0`.

## 3. Modele i wagi

Profile LLM (ID, repozytoria, porty i flagi serwera) są wyłącznie w
`configs/models.yaml`. Domyślny profil CLI to `local-llm`; wagi OCR domyślnie
`models/LightOnOCR-3-0.8B-mlx-8bit`.

Pobieranie wag OCR na Maca:

```bash
bash scripts/make-mlx-model-08b.sh   # 0.8B, szybki (domyślny w CLI)
bash scripts/make-mlx-model.sh       # 4B, dokładny
```

Backend wybiera źródło tekstu zmienną `WEB_OCR_BACKEND`: `text`, `cuda`, `mlx`.
Dane konkursowe mają warstwę tekstową, więc `text` jest najszybszą ścieżką
lokalną; OCR obrazowy jest potrzebny tylko dla prawdziwych skanów.
Szczegóły: `docs/BACKEND.md` i `docs/llm-runtime.md`.

## 4. Wydajność — zmierzone wartości

Pomiary na tym Macu, jeden plik
`przyklad_01/potwierdzenie_przelewu.pdf`, 1 strona, transkrypcja (`OCR_PROMPT=""`):

| Flow | Czas | Szczegóły |
|---|---:|---|
| `ocr-pdf2json`, 0.8B + LLM | **~9.5 s** | render 0.07 s, OCR 6.0 s, LLM 3.4 s |
| `/api/analyze`, 4B + LLM | **~55.5 s** | OCR 52.0 s, LLM ~3.3 s |
| `/api/analyze`, 0.8B + LLM (estymacja) | ~8–10 s | zgodne z pomiarem CLI |
| `lab predict-one`, tekst + LLM | ~5.2 s wall | LLM 4.6 s |
| `lab run`, 3 dokumenty, tekst + LLM | 18.1 s | 10.3 / 4.5 / 3.3 s na dokument |
| `lab models-check` | 0.63 s | health + constrained output |

Log llama.cpp (`work/servers/local-llm.log`) dla 4B/8B pokazuje typowo
~640 tokenów/s w prompt eval i ~68 tokenów/s w decode.

`18.1 s` z `lab run` to **suma dla 3 dokumentów**, nie czas jednego dokumentu.

Jakość: 0.8B jest szybki, ale na przykładzie zwrócił
`numer_transakcji: "ZREALIZOWANO"` zamiast `CEN2604016344389`. 4B zwrócił wszystkie
pola poprawnie. Domyślny 0.8B jest więc wyborem szybkości, nie najwyższej
dokładności.

## 5. Jak mierzyć samodzielnie

CLI wypisuje czasy sam:

```text
render=0.07s ocr=6.00s llm=3.43s total=9.49s
```

Dla API użyj `curl -w` (jeśli backend ma `API_TOKEN`, dodaj
`-H "X-API-Token: $API_TOKEN"`):

```bash
curl -sS -X POST http://localhost:8000/api/analyze \
  -F 'client_token=benchmark' -F 'doc_class=przelew' \
  -F 'client_doc_id=bench-przelew-1' \
  -F "file=@$DATA_ROOT/dane/przyklad_01/potwierdzenie_przelewu.pdf" \
  -o "$REPO_ROOT/work/e2e.json" \
  -w 'http=%{http_code} total=%{time_total}s\n'
```

Dla `lab`:

```bash
time uv run lab predict-one \
  --set przyklad_01 --class potwierdzenie_przelewu \
  --model local-llm --no-manage-server \
  --data-root "$DATA_ROOT"
```

`--data-root` musi wskazywać katalog **nad** `dane/`, nie sam `dane/`.

Szczegóły per dokument:

```bash
cat work/runs/<run>/usage.json
```

Pola: `prompt_tokens`, `completion_tokens`, `seconds`, `calls`, `retries`, `error`.
Logi serwera LLM:

```bash
tail -f work/servers/local-llm.log
```

## 6. Badawczy CLI `lab`

```bash
uv run lab --help
```

Najważniejsze komendy:

| Komenda | Zastosowanie |
|---|---|
| `models-check --models local-llm --no-manage-server` | health, structured output, tokeny, sekundy |
| `predict-one --set ... --class ... --model local-llm` | jeden dokument, pełny pipeline tekst + LLM |
| `run --config configs/experiments/E0_baseline.yaml --model local-llm --split all --limit 1` | krótki run z F1 |
| `board` | tabela wyników z `work/runs/` |
| `split`, `eval` | narzędzia badawcze |
| `collect`, `plots`, `report`, `ocr-prepare`, `ocr-run`, `ocr-eval` | stuby (`NotImplementedError`) |
| `ocr-smoke` | dymny test OCR (jeden silnik, jeden poziom szumu) |

Uwaga: `lab run` czyta warstwę tekstową (`pdfplumber`), nie robi OCR obrazowego.
Pełny obrazowy flow idzie przez `ocr-pdf2json` albo `/api/analyze`.

## 7. Typowe błędy

| Objaw | Przyczyna / fix |
|---|---|
| `LLM server ... is not running` | `uv run lab serve --model local-llm` |
| `OCR weights not found` | `bash scripts/make-mlx-model-08b.sh` |
| `no PDF found for przyklad_01/...` | zły `--data-root`; musi zawierać `dane/` |
| `no split found at work/splits.json` | dodaj `--split all` albo `lab split` |
| `no valid JSON produced` | sprawdź `work/runs/<run>/raw/` i `usage.json` → `error` |
| `structured=False` | model nie wspiera JSON Schema (np. bielik) |
| `llama-server not found in PATH` | zainstaluj llama.cpp / sprawdź PATH |
| frontend pokazuje tylko "Podgląd dokumentu" | ZIP nie zawiera plików PDF albo stare wersje utilsu ZIP |
