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
                runów, leaderboard.
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
