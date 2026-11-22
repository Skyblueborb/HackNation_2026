# Uruchomienie przetwarzania

Komenda do uruchomienia z katalogu `/opt/solution`:

```bash
sudo docker compose --profile batch run --rm batch
```

Komenda czyta wszystkie pliki PDF z `/opt/solution/input` (rekurencyjnie,
razem z podkatalogami spraw) i zapisuje wyniki do `/opt/solution/output`,
odtwarzając to samo drzewo katalogów. Każdy JSON ma nazwę pliku PDF, któremu
odpowiada (`input/case1/odwolanie.pdf` → `output/case1/odwolanie.json`).

Dokument, który nie należy do żadnej ze znanych klas (odwołanie,
pełnomocnictwo, potwierdzenie przelewu), dostaje **pusty JSON** (`{}`).

Komenda jest nieinteraktywna, kończy się sama i wypisuje postęp oraz
podsumowanie (`[done] N file(s), M failure(s)`). Błąd jednego dokumentu nie
przerywa przebiegu — ten plik dostaje `{}`, reszta jest przetwarzana dalej.

## Z jakich usług korzysta

| Element | Gdzie działa |
|---|---|
| Ekstrakcja tekstu z PDF (pdfplumber) | serwer GPU, przez API |
| Klasyfikacja dokumentu (reguły + profil n-gramowy) | serwer GPU, przez API |
| LLM do ekstrakcji pól (**Qwen3-8B**, Apache-2.0, kwantyzacja Q4_K_M) | serwer GPU NVIDIA, `llama.cpp` |

LLM nie jest usługą komercyjną — to ten sam otwarty model (`Qwen/Qwen3-8B-GGUF`)
postawiony na `llama.cpp` na wynajętej maszynie z kartą NVIDIA. Ta maszyna
wystawia API (`ocr-api serve`), a adres i klucz dostępu są w
`/opt/solution/.env` jako `OCR_SERVICE_URL` i `OCR_SERVICE_KEY`.

Sprawdzenie, czy usługa odpowiada (powinno zwrócić JSON, nie błąd połączenia):

```bash
source /opt/solution/.env && curl -s "$OCR_SERVICE_URL/health"
```

Jeśli to nie odpowiada, przetwarzanie zapisze puste pliki JSON — patrz
`docs/vm-deploy.md`.

## Interfejs graficzny (opcjonalny, nie jest potrzebny do oceny)

```bash
sudo docker compose up -d        # http://<adres-ip>:8080
```
