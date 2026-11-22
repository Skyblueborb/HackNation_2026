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
| Ekstrakcja tekstu z PDF (pdfplumber) | lokalnie na tej maszynie, bez GPU |
| Klasyfikacja dokumentu | lokalnie, reguły + profil n-gramowy |
| LLM do ekstrakcji pól (**Qwen3-8B**, Apache-2.0, kwantyzacja Q4_K_M) | zewnętrzny serwer GPU NVIDIA, API zgodne z OpenAI |

LLM nie jest usługą komercyjną — to ten sam otwarty model (`Qwen/Qwen3-8B-GGUF`)
postawiony na `llama.cpp` na wynajętej maszynie z kartą NVIDIA, wołany po HTTP.
Adres i ewentualny klucz są w `/opt/solution/.env`; dostęp do serwera GPU
utrzymuje usługa `o2j-llm-tunnel.service` (tunel SSH, startuje sama po
restarcie maszyny).

Sprawdzenie, czy LLM odpowiada (powinno zwrócić JSON, nie błąd połączenia):

```bash
curl -s http://localhost:8082/health
```

Jeśli to nie odpowiada, przetwarzanie zapisze puste pliki JSON — patrz
`docs/vm-deploy.md`.

## Interfejs graficzny (opcjonalny, nie jest potrzebny do oceny)

```bash
sudo docker compose up -d        # http://<adres-ip>:3000
```
