# `lab model-check` — kompletny przewodnik

`lab model-check` to harness do oceny modeli OCR i LLM na danych konkursowych.
Dla wybranych dokumentów robi trzy niezależne pomiary, zapisuje surowy tekst
OCR i wyniki JSON, mierzy czasy oraz porównuje JSON z goldem.

Główny cel: szybko odpowiedzieć, czy zły wynik to wina OCR, LLM, czy ich
połączenia — i na tej podstawie zmienić parametry.

## 1. Co dokładnie robi

Dla każdego dokumentu wykonuje do trzech sond:

| Sonda | Co robi | Co daje |
|---|---|---|
| `ocr` | PDF → OCR | plik `<stem>.ocr.txt`, CER/WER względem warstwy tekstowej, czasy render + OCR |
| `llm` | warstwa tekstowa PDF → LLM → JSON | F1 modelu językowego na czystym tekście, czas LLM |
| `e2e` | PDF → OCR → LLM → JSON | F1 całego pipeline'u, czasy render + OCR + LLM |

Dokładność JSON liczy istniejący ewaluator `lab.eval.metrics`. Harness nie ma
własnego scoringu. Headline w raporcie to `f1_skip` dla trybu `exact` i `fuzzy`.
W `metrics.json` są też pozostałe polityki nulli (`f1_tp`, `f1_strict`).

## 2. Wymagania

1. **Dane.** Katalog z `dane/przyklad_*` i/lub `dane/skany/...`.
   `configs/paths.yaml` może wskazywać nieistniejący katalog — wtedy podaj
   `--data-root` albo ustaw `O2J_DATA_ROOT`.
   W tym środowisku dane leżą w
   `/Users/skyblueborb/Projects/hacknation-2026`.
2. **Wagi OCR.** Domyślnie używane są oba lokalne modele MLX, jeśli istnieją:
   `models/LightOnOCR-3-0.8B-mlx-8bit` i
   `models/LightOnOCR-3-4B-mlx-8bit`. Można podać własne `--ocr-model`.
3. **Serwer LLM.** Harness nie startuje serwerów. Profil `local-llm` wymaga
   działającego `uv run lab serve --model local-llm` (port 8081).
   `qwen3-8b-l4` wymaga serwera na portcie 8082. Harness sprawdza `/health`
   i kończy błędem z komendą startową, jeśli serwer nie odpowiada.
4. **Środowisko.** `uv sync --extra local --extra serve --extra lab`.

## 2b. Korpus `borbelka`

Katalog `testy-dla-borbelka/` ma strukturę zestawów jak `przyklad_*`:

```text
testy-dla-borbelka/
  01/  <hash>.pdf + <hash>.json   (3–4 dokumenty)
  02/  ...
  ...
  -1/  <hash>.pdf + <hash>.json   (dokumenty negatywne, gold {})
  _results/                        (wyniki harnessu, nie dane)
```

Klasa jest wywnioskowana z kształtu gold JSON:

- `OdwolanieKIO` → `odwolanie`
- `mocodawca` → `pelnomocnictwo`
- `przelew_bankowy` → `potwierdzenie_przelewu`
- `{}` → `nieznany` (dokument ma zostać odrzucony)

Uruchomienie losowych zestawów:

```bash
uv run lab model-check \
  --data-root /Users/skyblueborb/Projects/HackNation_2026 \
  --corpus borbelka \
  --count 5 \
  --random \
  --seed 42 \
  --analysis e2e \
  --ocr-model models/LightOnOCR-3-0.8B-mlx-8bit \
  --verbose
```

`--data-root` to katalog repo, nie `dane/`. Wyniki lądują w `work/model-check/` albo pod wskazanym `--out-dir`.

## 2c. Harness przez backend proxy

Harness może wysyłać pliki do lokalnego backendu z `WEB_OCR_BACKEND=remote`.
Wtedy backend działa jako proxy do OCR+LLM na L4 — nie ładujesz wag lokalnie:

```bash
uv run lab model-check \
  --data-root /Users/skyblueborb/Projects/HackNation_2026 \
  --corpus przyklad \
  --count 10 \
  --remote http://127.0.0.1:8000 \
  --api-token <BACKEND_API_TOKEN> \
  --out-dir /Users/skyblueborb/Projects/HackNation_2026/work/model-check-remote \
  --verbose
```

`--api-token` czyta też zmienną `O2J_API_TOKEN`. W tym trybie dostępny jest
tylko pomiar `e2e`; wiersz w `summary.md` ma `OCR=remote`, `LLM=remote`.
Pozostałe tryby (`llm`, `ocr`) wymagają lokalnych modeli.

## 3. Uruchamianie

### Najprostszy smoke test

```bash
cd /Users/skyblueborb/Projects/HackNation_2026
uv run lab serve --model local-llm        # terminal 1

uv run lab model-check \
  --data-root /Users/skyblueborb/Projects/hacknation-2026 \
  --corpus przyklad \
  --count 2 \
  --analysis all
```

To robi 2 zestawy × 3 sondy dla dwóch modeli OCR i jednego profilu LLM.
Na 4B to może potrwać kilkanaście minut. Na szybki test dodaj
`--ocr-model models/LightOnOCR-3-0.8B-mlx-8bit`, żeby ograniczyć jedną oś.

### Tylko skany

```bash
uv run lab model-check \
  --data-root /Users/skyblueborb/Projects/hacknation-2026 \
  --corpus skany \
  --count 3 \
  --ocr-model models/LightOnOCR-3-4B-mlx-8bit \
  --llm-profile local-llm \
  --analysis e2e,ocr
```

Dla skanów sonda `llm` jest `N/A` — nie ma warstwy tekstowej, którą można
podświetlić modelowi językowemu zamiast OCR.

### Losowa próbka

```bash
uv run lab model-check --corpus all --count 10 --random --seed 7
```

Ten sam `--seed` daje zawsze ten sam wybór zestawów.

### Konkretne zestawy

```bash
uv run lab model-check --sets przyklad_01,przyklad_07
```

### Konkretne pliki PDF

```bash
uv run lab model-check \
  --pdf /Users/skyblueborb/Projects/hacknation-2026/dane/przyklad_02/odwolanie.pdf \
  --pdf /Users/skyblueborb/Projects/hacknation-2026/dane/skany/odwolania/0001/0001.pdf
```

`--pdf` musi wskazywać plik pod `<data-root>/dane`. Zestaw wyprowadzany jest
z katalogu nadrzędnego, klasa — z nazwy pliku lub katalogu `skany`.

### Baseline tekstowy bez OCR

```bash
uv run lab model-check --ocr-model text --analysis e2e,llm
```

`text` czyta warstwę tekstową PDF zamiast modelu OCR. Dzięki temu widać, jak
wiele F1 traci LLM przez sam OCR.

## 4. Opcje

| Opcja | Domyślnie | Znaczenie |
|---|---|---|
| `--data-root PATH` | `configs/paths.yaml` / `O2J_DATA_ROOT` | Katalog zawierający `dane/` |
| `--corpus` | `all` | `przyklad`, `skany`, `borbelka` albo `all` |
| `--count N` | `5` | Liczba zestawów; `0` = wszystkie |
| `--random` | off | Losuj zestawy zamiast brać pierwsze N |
| `--seed INT` | `42` | Ziarno losowania |
| `--sets IDS` | — | Komma-list zestawów, np. `przyklad_01,przyklad_07` |
| `--pdf PATH` | — | Konkretny PDF; powtarzalne |
| `--ocr-model PATH` | oba lokalne MLX | Wagi MLX albo `text`; powtarzalne |
| `--llm-profile ID` | `local-llm` | Profil z `configs/models.yaml`; powtarzalne |
| `--analysis LIST` | `all` | `e2e`, `ocr`, `llm`, `all` |
| `--out-dir PATH` | `work/model-check` | Katalog główny wyników |
| `--verbose` | off | Szczegółowe logi debugowe (domyślnie są logi INFO) |

Harness zawsze zapisuje artefakt OCR. Nie ma osobnej flagi `--save-ocr` —
ta flaga należy do `ocr-pdf2json`, z którego mechanizmów (`run_document`,
`write_ocr_text`) harness korzysta.

## 4b. Logi w trakcie działania

Harness domyślnie loguje postęp na stderr w formacie:

```text
2026-11-22 00:15:10,123 INFO model-check run dir=... cases=3 analyses=e2e,ocr,llm combos=6
2026-11-22 00:15:10,124 INFO model-check [1/6] analysis=e2e ocr=LightOnOCR-3-4B-mlx-8bit llm=local-llm
2026-11-22 00:15:10,200 INFO model-check case przyklad_01/odwolanie analysis=e2e
2026-11-22 00:16:02,900 INFO model-check   render=0.01s ocr=52.30s llm=10.07s total=62.38s status=ok
2026-11-22 00:16:03,100 INFO model-check   scored=1 exact_f1_skip=0.8123 fuzzy_f1_skip=0.8400 skipped=0
```

Widać więc, który etap trwa, dla którego dokumentu i ile zajął. Dodanie
`--verbose` ustawia poziom `DEBUG` i pokazuje dodatkowe szczegóły.
Brakujące PDF-y są wpisywane do `data_skipped` i logowane jako ostrzeżenie.

## 5. Struktura wyników

```text
work/model-check/<timestamp>-<seed>/
  config.json                  rozwiązane opcje i wybrane dokumenty
  summary.json                 wiersze dla wszystkich kombinacji
  summary.md                   tabela porównawcza
  <analysis>/
    <ocr-tag>/<llm-tag>/
      predictions/<set>/<gold_stem>.json
      ocr/<set>/<pdf_stem>.ocr.txt
      timings.json
      metrics.json
      score-gold/              wewnętrzny, przefiltrowany gold do oceny
      report.md
```

Dla sondy `ocr` tag LLM to `none`. Dla sondy `llm` tag OCR to `text`.

Nazwy gold są mapowane przez specs: `potwierdzenie_przelewu.pdf` porównywane
jest z `przelew.json`.

## 6. Jak czytać wyniki

`summary.md` ma jedną linię na kombinację: analiza, model OCR, profil LLM,
liczba plików, F1 exact, F1 fuzzy, F1 dla tekstu, binary F1 dla wartości
ścisłych, średni CER, średni czas całkowity i link do `report.md`.

Osobne F1 dla typów pól:

| Grupa | Pola | Score |
|---|---|---|
| `text` | `normalizer: text`, `name` — opisy, nazwy, tytuły, miejscowości | zwykłe F1 exact/fuzzy |
| `date` | `date_iso` — daty | binary: 1 albo 0 na pole |
| `identifier` | `digits`, `nrb26`, `bzp`, `ted` — KRS, NIP, REGON, numery | binary: 1 albo 0 na pole |
| `number` | `enum_int`, `money` — identyfikatory liczbowe, kwoty | binary: 1 albo 0 na pole |
| `other` | pola bez rozpoznanego normalizera | binary: 1 albo 0 na pole |
| `strict` | suma `date` + `identifier` + `number` + `other` | binary: 1 albo 0 na pole |

Dla wartości ścisłych nie ma częściowego dopasowania. Pole dostaje `1`, jeśli
wynik `exact` to `TP` albo `TN`, oraz `0` przy `FP` albo `FN`. Agregat grupy to
średnia z tych zer i jedynek — więc np. `0.8` oznacza 4 poprawne pola na 5.
W `report.md` są tabele grup oraz lista wyników dla każdego pola.

`report.md` w katalogu kombinacji ma:

- F1 i liczbę ocenionych plików,
- `data_skipped` — dokumenty pominięte, bo brakowało pliku lub golda,
- czasy: `mean`, `median`, `p95`, `sum` dla `render`, `ocr`, `llm`, `total`,
- średni CER z proxy OCR (tylko `przyklad_*`),
- pięć najgorszych rozbieżności pól: `gold` vs `pred`.

Typowe rozumowanie:

| OCR | LLM | E2E | Diagnoza | Co zmienić |
|---|---|---|---|---|
| zły | dobry | zły | wina OCR | wagi, prompt/DPI, `--ocr-model text` jako kontrola |
| dobry | zły | zły | wina LLM | `--llm-profile`, prompt, schemat |
| dobry | dobry | zły | tylko kombinacja | porównaj tekst z `.ocr.txt` z warstwą tekstową |
| dobry | dobry | dobry | dane nie są problemem | zwiększ `--count` lub użyj `--random` |

Przykład: `CER` rośnie przy 0.8B, a F1 `llm` na tym samym zestawie jest
wysokie. Otwórz `ocr/<set>/<stem>.ocr.txt` — zobaczysz, które słowa model
przepisał źle. Zmiana promptu OCR albo przejście na 4B powinno poprawić `e2e`,
bez ruszania LLM.

Jeśli `llm` jest niskie nawet na czystej warstwie tekstowej, problem leży po
stronie modelu językowego lub promptu ekstrakcji, nie po stronie OCR.

## 7. Czym jest `pdfplumber` i dlaczego skany są `N/A`

`pdfplumber` czyta **warstwę tekstową** zapisaną w cyfrowo wygenerowanym PDF.
Nie analizuje pikseli i nie robi OCR. Dla plików `przyklad_*` daje dokładny
tekst w milisekundy. Harness używa go do trzech rzeczy:

1. referencji do CER/WER (proxy jakości OCR),
2. wejścia do sondy `llm`,
3. baseline'u `--ocr-model text`.

Pliki w `dane/skany/*/0001/` nie mają warstwy tekstowej — to czyste obrazy.
Dlatego dla nich CER/WER i sonda `llm` są oznaczone `N/A`, a nie zerem.
Dostajesz natomiast `.ocr.txt`, czasy OCR i F1 dla `e2e`.

CER/WER to_proxy, nie ręcznie sprawdzona prawda: zakłada, że warstwa tekstowa
jest poprawna. Jeśli PDF ma błędną warstwę, wskaźnik może kłamać — wtedy
zfajrz do `.ocr.txt` i do gold JSON.

## 8. Zmiana parametrów i powtórzenie jednej osi

Harness nie kasuje poprzednich uruchomień — każdy dostaje osobny katalog
`<timestamp>-<seed>`. Można uruchomić tylko jedną oś i porównać raporty:

```bash
# tylko OCR, 0.8B, 5 przykładów
uv run lab model-check --analysis ocr --count 5 \
  --ocr-model models/LightOnOCR-3-0.8B-mlx-8bit

# tylko LLM, inny profil, te same zestawy
uv run lab model-check --analysis llm --sets przyklad_01,przyklad_02 \
  --llm-profile qwen3-8b-l4
```

W `summary.md` obu runów porównaj odpowiednie kolumny. Nie trzeba robić pełnej
macierzy za każdym razem.

## 9. Znane ograniczenia

- 4B jest wolny: około 50 s na stronę. Pełna macierz na 180 dokumentach jest
  kosztowna — zacznij od `--count 2` albo `--count 5`.
- `configs/paths.yaml` w tym repozytorium wskazuje nieistniejący katalog.
  Zawsze podawaj `--data-root` albo `O2J_DATA_ROOT`.
- Serwery LLM nie są startowane automatycznie. Harness tylko sprawdza health.
- Proxy CER/WER istnieje tylko dla `przyklad_*`.
- Brakujące PDF-y i goldy są pomijane i wpisywane do `data_skipped`; błędy
  modelu (brak predykcji) liczą się jako `missing_pred`.
- Uruchomienie jest szeregowe — jeden model OCR i jeden klient LLM naraz.

## 10. Rozwiązywanie problemów

| Objaw | Przyczyna | Fix |
|---|---|---|
| `data root not found` | zła ścieżka w `configs/paths.yaml` | `--data-root /Users/skyblueborb/Projects/hacknation-2026` |
| `LLM server ... is not running` | brak serwera | `uv run lab serve --model local-llm` |
| `no documents matched the selection` | brak PDF-ów w wybranych zestawach | zmień `--corpus`/`--sets` |
| `N/A` w CER dla skanów | brak warstwy tekstowej | to oczekiwane; patrz `.ocr.txt` i `e2e` |
| `missing_pred` w metrykach | model nie zwrócił JSON | sprawdź `report.md` i logi OCR/LLM |
