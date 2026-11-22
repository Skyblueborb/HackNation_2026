# Wdrożenie na VM-ce organizatora (Ubuntu 24.04, 2 vCPU, bez GPU)

Wymagania organizatora: całość w `/opt/solution`, `RUN.md` z jedną
nieinteraktywną komendą, `input/` → `output/`, usługi w tle wstają po
restarcie. Parametry maszyny i zasady oceny: `VM.md` w repo konkursowym.

Podział pracy: **VM-ka tylko wysyła PDF-y i zapisuje JSON-y**, cały OCR,
klasyfikację i LLM liczy wynajęty serwer NVIDIA przez `ocr-api serve`
(`WEB_OCR_BACKEND=remote` / `OCR_SERVICE_URL`). Lokalny `llama-server` na 2
vCPU nie zmieściłby się w limicie 45 minut na 150 plików. Postawienie serwera
GPU: `docs/gpu-server/README.md` i `scripts/gpu-server-bootstrap.sh`.

## 1. Kod w `/opt/solution`

```bash
cd /opt/solution
git clone <adres-repo> .          # katalog należy do Waszego konta, bez sudo
cp .env.example .env
```

W `.env` ustawić:

```ini
WEB_OCR_BACKEND=remote
OCR_SERVICE_URL=http://<ip-serwera-gpu>:8000
OCR_SERVICE_KEY=<API_KEY z gpu-server-bootstrap.sh>
WEB_PORT=8080            # VM wystawia do internetu tylko 80/443/8000/8080
API_TOKEN=<token GUI>
```

`input/` i `output/` już istnieją — nie usuwać, nie zmieniać nazw.

## 2. Połączenie z serwerem GPU

Nie ma tunelu SSH ani portu LLM-a wystawionego do świata: VM woła `ocr-api`
na serwerze GPU po HTTP, z kluczem w nagłówku `X-API-Key`. Sam `llama-server`
(8082) zostaje zamknięty na localhoście serwera GPU.

```bash
source .env
curl -s "$OCR_SERVICE_URL/health"        # musi odpowiedzieć
```

Po stronie serwera GPU `lab serve` (LLM) i `ocr-api serve` muszą działać w
czasie oceny — `scripts/gpu-server-bootstrap.sh` startuje jedno i drugie i
wypisuje gotową komendę dla klienta. Skrypt trzyma procesy w pierwszym planie,
więc na serwerze GPU odpalać go pod `tmux` (albo opakować w usługę systemd),
inaczej zniknie razem z sesją SSH.

Jeśli serwer GPU nie odpowiada w czasie oceny, wsad zapisze puste pliki JSON —
to najpoważniejsze ryzyko tego wdrożenia.

## 3. Obrazy Dockera zbudowane z góry

```bash
cd /opt/solution
docker compose build                      # api + web
docker compose --profile batch build      # obraz dla wsadu
```

Organizator nie gwarantuje, że pobieranie kilku GB w czasie oceny się uda —
dlatego build robimy przed odcięciem dostępu.

## 4. GUI (punktowane dodatkowo, nieobowiązkowe)

```bash
docker compose up -d        # http://<adres-ip>:8080 przy WEB_PORT=8080
```

## 5. Test dokładnie taki, jak zrobią to oceniający

```bash
cd /opt/solution
rm -rf output/* && mkdir -p input/case1
cp <kilka-pdf> input/case1/
sudo docker compose --profile batch run --rm batch     # komenda z RUN.md
find output -name '*.json' | head
```

Powtórzyć po restarcie maszyny:

```bash
sudo reboot        # odczekać 1-2 min
source .env && curl -s "$OCR_SERVICE_URL/health"   # serwer GPU odpowiada
sudo docker compose --profile batch run --rm batch
```

## Rozwiązywanie problemów

| Objaw | Przyczyna |
|---|---|
| wszystkie JSON-y puste (`{}`) | serwer GPU nieosiągalny — `curl "$OCR_SERVICE_URL/health"` |
| `[fail] ...: Connection refused` / `timed out` | `ocr-api serve` na GPU nie działa albo firewall blokuje 8000 |
| `[fail] ...: 401` / `403` | `OCR_SERVICE_KEY` nie zgadza się z `API_KEY` na serwerze GPU |
| wsad liczy lokalnie i się wlecze | `OCR_SERVICE_URL` puste w `.env` — wtedy batch liczy na VM-ce |
| wsad nie widzi plików | repo nie jest w `/opt/solution` (montaże `./input`, `./output` są względne do pliku compose) |
| GUI nie odpowiada z internetu | `WEB_PORT` poza 80/443/8000/8080 — tylko te porty są otwarte |
