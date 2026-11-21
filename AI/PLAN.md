# PLAN.md – testowanie flow i modeli (Odwołania2json, część AI)

Cel: w jednej powtarzalnej ramie porównać silniki OCR, modele LLM i warianty pipeline'u na danych UZP, a potem wybrać zestaw z najwyższym F1 na zbiorze **holdout**. Modele uruchamiamy lokalnie przez **llama.cpp**. Wszystko jest open source.

> Zasada nadrzędna: zmieniamy **jedną rzecz naraz**. Wariant zostaje tylko wtedy, gdy podnosi F1 na holdout.

---

## 0. Zasady

1. **Tylko open source.** Kod: MIT, Apache 2.0, BSD, MPL. Wagi modeli: Apache 2.0 lub MIT. Każdy komponent wpisujemy do `docs/LICENSES.md` w chwili dodania, nie na końcu.
2. **Wykluczone:** Llama i Gemma (licencje niestandardowe), Qwen2.5-3B (licencja badawcza), Surya i Marker (ograniczenia wag), LayoutLMv3 (wagi niekomercyjne), PyMuPDF (AGPL, unikamy ze względu na przyszłe wdrożenie w UZP).
3. **Holdout jest święty.** Nie patrzymy w jego dokumenty przy pisaniu promptów i regexów. Służy tylko do pomiaru.
4. **Każdy run jest odtwarzalny:** zapisujemy hash commita, plik modelu, kwantyzację, flagi serwera, hash promptu i konfiguracji.
5. **Brak danych = `null`.** Model ma prawo nie odpowiedzieć. Zgadywanie kosztuje podwójnie (FP i FN).

---

## 1. Stack testowy

| Warstwa | Narzędzie | Licencja |
|---|---|---|
| Serwer modeli | llama.cpp `llama-server` (API zgodne z OpenAI) | MIT |
| Przełączanie modeli (opcjonalnie) | llama-swap | MIT (sprawdź) |
| Klient | `openai` (Python SDK, tylko jako klient HTTP) | Apache 2.0 |
| Tekst z PDF | pypdfium2, pdfplumber | Apache/BSD, MIT (sprawdź) |
| OCR | OCRmyPDF + Tesseract 5 `pol`, RapidOCR (PP-OCRv5) | MPL-2.0, Apache 2.0 |
| Układ strony (wariant) | Docling | MIT |
| Schematy | Pydantic v2, datamodel-code-generator | MIT |
| Grounding i F1 rozmyte | rapidfuzz | MIT |
| Embeddingi few-shot | multilingual-e5-small (przez llama.cpp `--embedding` albo sentence-transformers) | MIT / Apache 2.0 (sprawdź) |
| Złe skany | Augraphy | MIT (sprawdź) |
| OCR – metryki CER/WER | jiwer | Apache 2.0 (sprawdź) |
| OCR – dodatkowe silniki | docTR, EasyOCR | Apache 2.0 (sprawdź) |
| Tabele wyników | pandas | BSD-3 |
| Wykresy | matplotlib (+ opcjonalnie seaborn) | licencja matplotlib (BSD-style) / BSD-3 |
| Konfiguracja eksperymentów | YAML + Typer (CLI) | MIT |

Licencje oznaczone „sprawdź” potwierdzić w pliku LICENSE przed oddaniem.

---

## 2. llama.cpp – instalacja i uruchomienie

### 2.1. Mac (development, Metal)

```bash
brew install llama.cpp            # albo build ze źródeł: cmake -B build && cmake --build build -j
llama-server --version
```

### 2.2. CPU (pomiar warunków organizatora)

Docker na Macu nie ma dostępu do Metal, więc kontener mierzy realny czas na CPU.

```bash
docker run --rm -p 8080:8080 -v $PWD/models:/models \
  ghcr.io/ggml-org/llama.cpp:server \
  -m /models/<model>.gguf -c 16384 --jinja --host 0.0.0.0 --port 8080 -t 8
```

Na Macu natywnie można też wymusić CPU flagą `-ngl 0` (zero warstw na GPU).

### 2.3. Uruchomienie serwera

```bash
# Metal, pełne offloadowanie, kontekst 16k, szablon czatu z modelu
llama-server -m models/qwen3-14b-q4_k_m.gguf \
  -c 16384 -ngl 99 --jinja --port 8081 --parallel 1

# Kilka modeli naraz = kilka portów (pilnuj RAM: 24 GB)
llama-server -m models/bielik-11b-v3-q4_k_m.gguf -c 16384 -ngl 99 --jinja --port 8082
```

- `--jinja` jest potrzebne, żeby użyć szablonu czatu z pliku GGUF (inaczej odpowiedzi bywają rozjechane).
- Pobieranie z Hugging Face: `llama-server -hf <repo>:Q4_K_M` (nazwy repo w sekcji 3 sprawdzić na HF).
- Jeden serwer = jeden model. Przy wielu modelach na zmianę użyj llama-swap albo skryptu, który restartuje serwer.

---

## 3. Modele do testu

RAM to orientacyjne wartości dla Q4_K_M plus kontekst. Na 24 GB naraz trzymamy najwyżej jeden model 14B albo dwa mniejsze.

| ID | Model | Źródło GGUF (sprawdź nazwę na HF) | Licencja | Kwant. | ~RAM | Rola | Prio |
|---|---|---|---|---|---|---|---|
| `qwen3-8b` | Qwen3-8B | `Qwen/Qwen3-8B-GGUF` | Apache 2.0 | Q4_K_M, Q5_K_M | 6–7 GB | szybki kandydat, zapas na CPU | P0 |
| `qwen3-14b` | Qwen3-14B | `Qwen/Qwen3-14B-GGUF` | Apache 2.0 | Q4_K_M | 10–11 GB | główny kandydat | P0 |
| `bielik-11b` | Bielik-11B v3.x Instruct | `speakleash/...-GGUF` lub Ollama `SpeakLeash/bielik-11b-v3.x-instruct` | Apache 2.0 + Terms of Use | Q4_K_M | 8–9 GB | najlepszy polski | P0 |
| `qwen3-30b-a3b` | Qwen3-30B-A3B (MoE) | `Qwen/Qwen3-30B-A3B-GGUF` | Apache 2.0 | Q4_K_M | ~19–20 GB | jakość + szybkość na CPU | P1 |
| `gpt-oss-20b` | gpt-oss-20B | `ggml-org/gpt-oss-20b-GGUF` | Apache 2.0 | MXFP4 | ~13–14 GB | porównanie | P1 |
| `mistral-small` | Mistral Small (tylko wersja na Apache 2.0) | sprawdź | sprawdź dla wersji | Q4_K_M | ~15 GB | porównanie | P2 |
| `qwen3-4b` | Qwen3-4B | `Qwen/Qwen3-4B-GGUF` | Apache 2.0 | Q4_K_M | 3–4 GB | klasyfikacja, słabe maszyny | P2 |

**Uwaga o API:** jeśli produkcyjnie wołamy ten sam otwarty model u dostawcy z UE (FAQ na to pozwala), lokalny GGUF jest jego wersją „do instalacji lokalnej”. Wyniki z kwantyzacji Q4 mogą być nieco gorsze niż z pełnej precyzji u dostawcy. Mierzymy oba i zapisujemy oba.

**Qwen3 i tryb myślenia:** dla structured output wyłączamy myślenie. Opcje (zależnie od wersji llama.cpp, sprawdź): `/no_think` na końcu wiadomości użytkownika albo `chat_template_kwargs: {"enable_thinking": false}` w żądaniu. Raz testujemy z włączonym, żeby sprawdzić, czy daje zysk F1.

---

## 4. Struktura katalogów

```
lab/
  configs/
    models.yaml            # endpointy i parametry modeli
    experiments/
      E1_baseline.yaml
      E2_candidates.yaml
      ...
  prompts/
    odwolanie.j2           # szablony Jinja2 per klasa
    pelnomocnictwo.j2
    potwierdzenie_przelewu.j2
    classify.j2
  cache/                   # wyniki etapów po sha256 pliku (tekst, OCR, kandydaci)
  runs/<data>_<exp>_<model>/
    manifest.json          # commit, model, kwant., flagi, hash promptu i configu
    pred/<plik>.json       # wynik kanoniczny
    pred/<plik>.meta.json  # pochodzenie pól, pewność
    raw/<plik>.txt         # surowa odpowiedź modelu (do debugowania)
    metrics.json           # F1 globalnie, per klasa, per pole
    errors.md              # lista pomyłek: pole, oczekiwane, otrzymane, plik
  leaderboard.md           # jedna linia na run, generowana automatycznie
  splits.json              # podział zestawów: dev / holdout
  ocr_bench/
    gt/                    # tekst wzorcowy stron (z warstwy tekstowej lub ręcznie przepisany)
    images/<poziom_szumu>/ # strony jako obrazy: clean, light, medium, heavy
    runs/<silnik>_<wariant>/  # tekst z OCR per strona + metrics.json
  results/
    llm_runs.csv           # zebrane metrics.json wszystkich runów LLM
    ocr_runs.csv           # zebrane metryki OCR
  reports/
    figures/*.png|*.svg    # wykresy porównawcze
    index.md               # raport z wykresami i tabelami (do README i prezentacji)
```

**Cache etapów** to klucz do szybkich testów: OCR i ekstrakcja tekstu liczą się raz na plik i wariant OCR. Eksperymenty z modelami i promptami wtedy nie powtarzają OCR.

---

## 5. Konfiguracja

### 5.1. `models.yaml`

```yaml
qwen3-14b:
  base_url: http://localhost:8081/v1
  model: qwen3-14b-q4_k_m
  file: models/qwen3-14b-q4_k_m.gguf
  license: Apache-2.0
  params: {temperature: 0, seed: 42, max_tokens: 2048}
  no_think: true
bielik-11b:
  base_url: http://localhost:8082/v1
  model: bielik-11b-v3-q4_k_m
  file: models/bielik-11b-v3-q4_k_m.gguf
  license: Apache-2.0 + Terms of Use
  params: {temperature: 0, seed: 42, max_tokens: 2048}
```

### 5.2. Eksperyment (`configs/experiments/E2_candidates.yaml`)

```yaml
name: E2_candidates
split: holdout              # dev podczas strojenia, holdout do pomiaru
ingest:
  text_layer: pdfplumber     # pdfplumber | pdfplumber_layout | docling
  ocr: tesseract_best        # tesseract_best | tesseract_fast | rapidocr | vote
  ocr_opts: {psm: 3, dpi: 300, deskew: true, rotate: true}
  pages: [1, 2, 3]
classify:
  method: rules              # rules | rules+llm | llm
  reject_threshold: 6
extract:
  model: qwen3-14b
  structured_output: true    # json_schema w żądaniu
  candidates: true           # kandydaci z regexów w promptcie
  fewshot: 0                 # 0 | 1 | 2 (z dev, nigdy z tego samego zestawu)
  retry_on_invalid: 1
post:
  normalize: true
  ground_null: false         # null, gdy wartość nie występuje w tekście
  cross_validate: false
```

Każdy wariant to kopia z jedną zmienioną flagą.

---

## 6. Klient llama.cpp ze schematem JSON

```python
from openai import OpenAI

def call_llm(m: dict, system: str, user: str, schema: dict) -> str:
    client = OpenAI(base_url=m["base_url"], api_key="sk-local")  # llama-server nie sprawdza klucza
    if m.get("no_think"):
        user += "\n/no_think"
    r = client.chat.completions.create(
        model=m["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "extraction", "schema": schema}},
        **m["params"],
    )
    return r.choices[0].message.content
```

- llama-server zamienia JSON Schema na gramatykę i wymusza format. Jeśli Twoja wersja nie przyjmuje `response_format` w tej postaci, użyj pola `json_schema` albo `grammar` (GBNF) w żądaniu, wg README `tools/server` w repo llama.cpp.
- Schemat: **płaski lub z jednym poziomem zagnieżdżenia**, bez `$ref`/`$defs` (konwersja do gramatyki bywa problematyczna). Każde pole `["string", "null"]`, opis po polsku z przykładem formatu.
- Kolejność pól w schemacie = kolejność generowania. Najpierw pola kontekstowe (np. typ dokumentu, strony), potem szczegóły.
- Ten sam klient działa z dostawcą UE: zmieniasz tylko `base_url`, `model` i klucz.

---

## 7. Warianty flow (ablacja)

Najpierw wybieramy model na E2, potem budujemy warianty na zwycięzcy.

| ID | Zmiana względem poprzedniego | Hipoteza |
|---|---|---|
| E1 | tekst/OCR + LLM zero-shot ze schematem | baza |
| E2 | + kandydaci z regexów (NIP, NRB, kwoty, daty, BZP) w promptcie | mniej pomyłek w cyfrach |
| E3 | + normalizacja do formatu referencji | punkty „za darmo” na formacie |
| E4 | + `null`, gdy wartość nie ma ugruntowania w tekście (rapidfuzz < 85) | wyższa precyzja |
| E5 | + few-shot 1–2 podobnych przykładów z dev | lepsze przypisanie ról |
| E6 | + tekst z układem (pdfplumber `layout=True` lub Docling) | lepsze pary etykieta–wartość w przelewach |
| E7 | + drugi silnik OCR, wybór wartości przechodzącej sumę kontrolną | odporność na skany |
| E8 | + walidacja krzyżowa w zestawie (pełnomocnik, kwota wpisu, odwołujący) | spójność trzech dokumentów |
| E9 | jedno wywołanie na dokument vs osobne na sekcje (strony/podmioty) | jakość przy długich odwołaniach |
| E10 | regexy tylko jako kandydaci vs regexy wpisane na sztywno (bez LLM dla pól formatowych) | który tryb lepszy dla NIP/NRB/kwot |

---

## 8. Ewaluacja

### 8.1. Podział danych

- ~39 zestawów × 3 dokumenty. Podział **po zestawach** (nie po plikach), żeby dokumenty jednej sprawy nie trafiły do dev i holdout jednocześnie: np. 27 dev / 12 holdout, zapisane w `splits.json` z seedem.
- Few-shot pobiera przykłady **wyłącznie z dev** i nigdy z tego samego zestawu.
- Dodatkowo: 10–20 obcych PDF-ów (faktury, umowy, losowe skany) do testu klasy `odrzucony`.
- Wersje „złych skanów” z Augraphy dla holdout jako osobny zbiór `holdout_noisy`.

### 8.2. Liczenie F1

Spłaszczamy JSON do par `ścieżka → wartość` (np. `pelnomocnicy[0].nazwisko`), normalizujemy obie strony i liczymy:

| Przewidziane | Wzorzec | Liczy się jako |
|---|---|---|
| wartość = wzorzec | wartość | TP |
| wartość ≠ wzorzec | wartość | FP + FN |
| wartość | `null` / brak | FP |
| `null` | wartość | FN |
| `null` | `null` | pomijane (flaga, bo nie wiemy, jak liczy UZP) |

Precision = TP / (TP + FP), Recall = TP / (TP + FN), F1 = 2PR / (P + R). Liczymy **micro-F1** globalnie i per klasa oraz F1 per pole.

Dwa tryby: `exact` (po normalizacji) i `fuzzy` (rapidfuzz ≥ 90). Decyzje podejmujemy na `exact`, bo nie wiemy, jak porównuje organizator.

Listy (np. kilku pełnomocników): dopasowanie elementów zachłanne po podobieństwie, potem porównanie pól. Kolejność w liście nie powinna mieć znaczenia, chyba że referencja wskazuje inaczej.

### 8.3. Co raportuje każdy run

- `metrics.json`: F1 exact i fuzzy (globalnie, per klasa, per pole), trafność klasyfikacji, trafność odrzucania, odsetek niepoprawnego JSON, liczba retry.
- Czas: średni i maksymalny na dokument; osobno na Metal i na CPU.
- `errors.md`: 30 najczęstszych pomyłek z przykładami.
- Linia w `leaderboard.md`.

---

## 8A. Benchmark OCR

Cel: wybrać silnik i ustawienia OCR **niezależnie od LLM**, a potem sprawdzić, jak błędy OCR przekładają się na F1 pól.

### 8A.1. Skąd wzorzec tekstu (za darmo)

Dokumenty z warstwą tekstową dają gotowy wzorzec:

1. Wyciągamy tekst strony z warstwy tekstowej (pdfplumber) → `gt/<plik>_p<n>.txt`.
2. Renderujemy tę samą stronę do obrazu 300 dpi (pypdfium2) → OCR widzi „skan” bez warstwy tekstowej.
3. Nakładamy szum Augraphy w czterech poziomach: `clean`, `light` (lekkie rozmycie, szum), `medium` (przekrzywienie 1–3°, ksero, pieczątka), `heavy` (niska rozdzielczość 150 dpi, silny szum, plamy).
4. Dla prawdziwych skanów z danych (jeśli są) ręcznie przepisujemy 5–10 stron jako dodatkowy wzorzec `gt_real/`.

Wybieramy ok. 30–60 stron z dev (różne klasy, głównie strony 1–3). Holdout zostaje do testu końcowego całego pipeline'u.

### 8A.2. Silniki i warianty

| ID | Silnik / ustawienia | Licencja | Prio |
|---|---|---|---|
| `tess_best_psm3` | Tesseract 5 `pol`, `tessdata_best`, `--psm 3` | Apache 2.0 | P0 |
| `tess_best_psm4` | jw., `--psm 4` (kolumny, układ tabelaryczny) | Apache 2.0 | P0 |
| `tess_best_psm6` | jw., `--psm 6` (jeden blok tekstu) | Apache 2.0 | P0 |
| `tess_fast_psm3` | `tessdata_fast` | Apache 2.0 | P0 |
| `ocrmypdf_full` | OCRmyPDF + Tesseract best, `--deskew --rotate-pages --clean` | MPL-2.0 | P0 |
| `tess_pol_eng` | Tesseract `pol+eng` (nazwy firm, skróty) | Apache 2.0 | P1 |
| `rapidocr_v5` | RapidOCR + PP-OCRv5 latin (ONNX) | Apache 2.0 | P1 |
| `docling_tess` | Docling z TesseractCli (układ + kolejność czytania) | MIT | P1 |
| `doctr` | docTR (domyślne modele) | Apache 2.0 (sprawdź) | P2 |
| `easyocr_pl` | EasyOCR `pl` | Apache 2.0 (sprawdź) | P2 |
| `vote_fields` | Tesseract + RapidOCR, wybór wartości przechodzącej sumę kontrolną | — | P1 |
| `preproc_*` | warianty obróbki: binaryzacja Sauvola/Otsu, usunięcie kanału czerwonego (pieczątki), 300 vs 400 dpi | — | P1 |

### 8A.3. Metryki OCR

| Metryka | Jak | Po co |
|---|---|---|
| **CER** | jiwer, po normalizacji białych znaków | ogólna jakość znaków |
| **WER** | jiwer | jakość słów |
| **Polskie znaki** | recall znaków `ąćęłńóśźżĄĆĘŁŃÓŚŹŻ` (wyrównanie przez rapidfuzz/jiwer) | czy silnik nie gubi diakrytyków |
| **Cyfry** | CER liczony tylko na cyfrach | NIP, NRB, kwoty, daty |
| **F1 pól regułowych** | regexy + walidatory na tekście z OCR vs na tekście wzorcowym (NIP, NRB, kwoty, daty, BZP) | to, co realnie trafia do JSON |
| **Sumy kontrolne** | odsetek znalezionych NIP/NRB z poprawną sumą | szybki wskaźnik jakości cyfr |
| **Czas** | s/stronę na CPU (Docker) i na Macu | wykonalność u organizatora |
| **RAM** | szczyt pamięci procesu | wykonalność u organizatora |

Wszystko liczymy osobno dla każdego poziomu szumu i osobno dla każdej klasy dokumentu.

### 8A.4. Most OCR → F1 całego pipeline'u

Dla 2–3 najlepszych silników puszczamy pełny pipeline (zwycięski model LLM, ta sama konfiguracja) na `holdout` i `holdout_noisy`. Decyduje F1 pól, nie CER: silnik z gorszym CER może dawać lepsze F1, jeśli lepiej czyta cyfry i etykiety.

### 8A.5. Komendy

```bash
lab ocr-prepare --pages 50 --levels clean,light,medium,heavy --seed 42   # gt + obrazy
lab ocr-run --engines tess_best_psm3,tess_best_psm4,ocrmypdf_full,rapidocr_v5
lab ocr-eval                     # metrics.json per silnik i poziom → results/ocr_runs.csv
```

---

## 8B. Wykresy porównawcze

Wykresy generuje `lab plots` z plików `results/*.csv` (zbieranych automatycznie z `metrics.json`). Zapis do `reports/figures/` w PNG (prezentacja) i SVG (README), plus `reports/index.md` z wykresami i tabelami.

### 8B.1. Lista wykresów

| Plik | Typ | Co pokazuje |
|---|---|---|
| `ocr_cer_by_noise.png` | linia: oś X poziom szumu, linia na silnik | jak szybko silnik degraduje się na gorszych skanach |
| `ocr_digits_diacritics.png` | słupki grupowane: silnik × (CER cyfr, recall polskich znaków) | czytanie cyfr i diakrytyków |
| `ocr_field_f1.png` | słupki: F1 pól regułowych per silnik (kolor = poziom szumu) | co OCR daje dla JSON |
| `ocr_speed_vs_cer.png` | punktowy: s/stronę vs CER, etykieta = silnik | kompromis jakość–czas |
| `llm_f1_by_model.png` | słupki: micro-F1 exact per model, wąs = F1 fuzzy | wybór modelu |
| `llm_f1_by_class.png` | słupki grupowane: klasa × model | gdzie model jest słaby |
| `field_heatmap.png` | heatmapa: pole × wariant/model, kolor = F1 | które pola leżą |
| `ablation_waterfall.png` | wodospad: E1 → E10, zmiana F1 po każdym kroku | co naprawdę pomaga (dobre na pitch) |
| `pareto_f1_time.png` | punktowy: s/dokument (CPU) vs F1, linia frontu Pareto | najlepszy wariant przy limicie czasu |
| `quant_f1.png` | słupki: Q4_K_M / Q5_K_M / Q6_K, F1 i czas | wybór kwantyzacji |
| `local_vs_api.png` | słupki parami: ten sam model lokalnie (GGUF) vs u dostawcy UE | czy lokalna wersja trzyma jakość |
| `noise_pipeline_f1.png` | słupki: F1 pipeline'u na `holdout` vs `holdout_noisy` per silnik OCR | odporność całego systemu |
| `classification_confusion.png` | macierz pomyłek: 3 klasy + `odrzucony` | jakość klasyfikacji i odrzucania |
| `errors_top_fields.png` | słupki poziome: 15 pól z największą liczbą pomyłek (FP/FN skumulowane) | priorytety poprawek |

### 8B.2. Zasady wykresów

- Jeden wykres = jedno pytanie. Tytuł mówi wniosek, np. „Qwen3-14B najlepszy na pełnomocnictwach”, a nie „Wyniki”.
- Oś F1 od 0 do 1 (albo jawnie oznaczony zakres, gdy różnice są małe).
- Na każdym wykresie: zbiór (`holdout` / `holdout_noisy`), data i commit w stopce.
- Te same kolory dla tego samego modelu/silnika na wszystkich wykresach (mapa kolorów w `configs/plot_colors.yaml`).
- Bez wykresów kołowych i 3D.

### 8B.3. Przykład (szkic)

```python
import pandas as pd, matplotlib.pyplot as plt

df = pd.read_csv("results/llm_runs.csv")          # kolumny: run_id, model, variant, split, f1_exact, f1_fuzzy, sec_per_doc
d = df[(df.split == "holdout") & (df.variant == "E2")].sort_values("f1_exact")
fig, ax = plt.subplots(figsize=(7, 4))
ax.barh(d.model, d.f1_exact)
ax.errorbar(d.f1_fuzzy, d.model, fmt="|", color="black", label="F1 fuzzy")
ax.set_xlim(0, 1); ax.set_xlabel("micro-F1 (exact, holdout)")
ax.set_title(f"Najlepszy model na E2: {d.iloc[-1].model}")
fig.tight_layout(); fig.savefig("reports/figures/llm_f1_by_model.png", dpi=200)
```

### 8B.4. Komendy

```bash
lab collect                    # runs/*/metrics.json + ocr_bench/runs → results/*.csv
lab plots                      # wszystkie wykresy z 8B.1 → reports/figures/
lab report                     # reports/index.md: wykresy + leaderboard + wnioski do uzupełnienia
```

---

## 9. Kolejność eksperymentów

| Faza | Co | Zbiór | Wynik fazy |
|---|---|---|---|
| A (P0) | Ewaluator + splits + cache OCR; sprawdzenie na referencjach (pred = gold → F1 = 1.0) | — | działający pomiar |
| B (P0) | Benchmark OCR wg 8A: Tesseract best/fast, psm 3/4/6, OCRmyPDF na 4 poziomach szumu; potem RapidOCR, Docling, vote (P1) | dev (strony) | 2–3 finalistów OCR, pierwsze wykresy OCR |
| C (P0) | Modele na E2: qwen3-8b, qwen3-14b, bielik-11b (Q4_K_M) | holdout | 1–2 finalistów |
| D (P1) | Ablacja E3–E10 na zwycięzcy | holdout | konfiguracja finalna |
| E (P1) | Kwantyzacja zwycięzcy: Q4_K_M vs Q5_K_M vs Q6_K; myślenie on/off | holdout | wariant do wdrożenia |
| F (P1) | Czas na CPU w Dockerze + ten sam model u dostawcy UE | holdout | liczby do README |
| G (P1) | Most OCR → F1 (8A.4): finaliści OCR w pełnym pipelinie na `holdout` i `holdout_noisy`, obce PDF-y (odrzucanie) | holdout, holdout_noisy | wybrany OCR, lista znanych ograniczeń |
| H (P2) | Duże modele: qwen3-30b-a3b, gpt-oss-20b | holdout | czy warto zmienić |
| I (P1) | `lab collect && lab plots && lab report` po każdej fazie | — | aktualne wykresy do README i prezentacji |

---

## 10. Kryteria decyzji

1. Najwyższe micro-F1 exact na holdout.
2. Przy różnicy < 1 pkt wybieramy wariant prostszy, szybszy na CPU albo z mniejszą liczbą błędów JSON.
3. Żadne pole kluczowe (strony, kwota, rachunek, daty) nie może spaść o więcej niż 2 pkt względem poprzedniego zwycięzcy.
4. Działa na CPU w rozsądnym czasie (cel: poniżej kilku minut na dokument, do potwierdzenia z UZP).
5. Licencja potwierdzona i wpisana do `docs/LICENSES.md`.

---

## 11. Manifest runu (`manifest.json`)

```json
{
  "run_id": "2026-11-21T18-05_E2_qwen3-14b",
  "git_commit": "abc1234",
  "experiment": "configs/experiments/E2_candidates.yaml",
  "config_sha256": "...",
  "prompts_sha256": {"odwolanie": "...", "pelnomocnictwo": "...", "potwierdzenie_przelewu": "..."},
  "model": {"id": "qwen3-14b", "file": "qwen3-14b-q4_k_m.gguf", "file_sha256": "...", "license": "Apache-2.0"},
  "server": {"llama_cpp_version": "...", "flags": "-c 16384 -ngl 99 --jinja", "device": "metal"},
  "split": "holdout",
  "started": "...", "finished": "..."
}
```

---

## 12. Komendy (docelowo)

```bash
lab split --sets dane/ --holdout 12 --seed 42          # tworzy splits.json
lab ingest --config configs/experiments/E2_candidates.yaml   # wypełnia cache
lab run   --config configs/experiments/E2_candidates.yaml --model qwen3-14b
lab eval  --run runs/<id>                               # metrics.json, errors.md
lab board                                               # odświeża leaderboard.md
lab sweep --configs "configs/experiments/E*.yaml" --models qwen3-8b,qwen3-14b,bielik-11b

# OCR
lab ocr-prepare --pages 50 --levels clean,light,medium,heavy --seed 42
lab ocr-run --engines tess_best_psm3,tess_best_psm4,tess_best_psm6,tess_fast_psm3,ocrmypdf_full,rapidocr_v5
lab ocr-eval

# Wyniki i wykresy
lab collect && lab plots && lab report
```

`lab` to narzędzie badawcze. Produkcyjne `o2j` używa tego samego rdzenia i zwycięskiej konfiguracji.

---

## 13. Pułapki

- **Metal ≠ CPU.** Czasy z Maca nie mówią nic o komputerze biurowym. Mierz w Dockerze lub z `-ngl 0`.
- **Kontekst.** Za małe `-c` ucina dokument bez błędu. Loguj liczbę tokenów promptu i ostrzegaj powyżej 80% kontekstu.
- **Szablon czatu.** Bez `--jinja` część modeli (Qwen3, Bielik) odpowiada gorzej albo z artefaktami.
- **Gramatyka wymusza format, nie prawdę.** Bez `null` w schemacie model zmyśli wartość, żeby spełnić schemat.
- **Determinizm.** `temperature=0` i stały `seed`, `--parallel 1`. Mimo to wyniki mogą minimalnie się różnić między Metal i CPU.
- **RAM 24 GB.** Dwa serwery 14B naraz nie zmieszczą się. Testuj modele kolejno.
- **Przeuczenie na syntetykach.** Regexy pod etykiety i formaty z przepisów, nie pod układ konkretnego pliku.
- **Dane osobowe.** Logi surowych odpowiedzi trzymamy lokalnie, poza repo.

---

## 14. Plan godzinowy (osoba od AI)

| Kiedy | Zadanie | Gotowe, gdy |
|---|---|---|
| teraz – 14:30 | llama.cpp działa, pobrane qwen3-8b, qwen3-14b, bielik-11b; szkielet `lab/` | `curl localhost:8081/v1/models` odpowiada |
| 14:30 – 16:00 | `lab split`, `lab eval` (test pred = gold), cache ingest; `lab ocr-prepare` i benchmark Tesseract (P0) w tle | F1 = 1.0 na referencjach, pierwsze CER |
| 16:00 – 18:00 | prompty 3 klas, E1 i E2 na trzech modelach; `lab collect && lab plots` | pierwsza tabela w `leaderboard.md` i wykresy OCR + modeli (M1) |
| 18:00 – 22:00 | E3–E6 na zwycięzcy, analiza `errors.md`; OCR P1 (RapidOCR, Docling, vote) | konfiguracja z najwyższym F1, heatmapa pól (M2) |
| noc | E7–E10, most OCR → F1, kwantyzacja, czas na CPU, porównanie z API UE | wybrany model i OCR, wykres wodospadu i Pareto |
| ndz. 8:00 | `lab report` → wykresy do README i prezentacji | `reports/index.md` gotowy |
| ndz. do 9:00 | zamrożenie promptów i configu, przekazanie do `o2j` | freeze |
