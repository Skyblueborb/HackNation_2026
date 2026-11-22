# Postawienie serwerów na wynajętym GPU (Ubuntu 24.04 LTS, NVIDIA L4)

Dokładna, skopiuj-wklej instrukcja na świeżym Ubuntu 24.04 z kartą NVIDIA
(L4, 24 GB VRAM — profil `qwen3-8b-l4` w `configs/models.yaml` jest dobrany
pod ten GPU). Kontekst architektury: `docs/superpowers/specs/2026-11-21-cloud-gpu-split-design.md`.

Uruchomienie serwerów i połączenie z klienta robią trzy skrypty:
`scripts/gpu-server-bootstrap.sh` na L4 oraz `scripts/connect-gpu-backend.sh`
i `scripts/connect-gpu-frontend.sh` w dwóch terminalach na kliencie. Kroki 1-2
poniżej to jednorazowe przygotowanie maszyny, krok 3 to już tylko ich
odpalenie.

Zasada bezpieczeństwa: `ocr-api serve` wystawia port 8000 publicznie
(`--host 0.0.0.0`) i chroni go tylko `API_KEY`/`X-API-Key` — nie ma za nim
firewalla ani SSH. `llama-server` (8082) zostaje na `localhost` i nie ma
żadnej autoryzacji — nigdy nie wystawiaj tego portu na świat.

## 0. Wymagania

- Instancja Ubuntu 24.04 LTS z GPU NVIDIA (L4) i dostępem `sudo`.
- Dostęp SSH kluczem (nie hasłem).

## 1. Sterownik NVIDIA i firewall

```bash
nvidia-smi    # musi pokazać kartę; jeśli "command not found":
sudo apt update && sudo apt install -y nvidia-driver-550 && sudo reboot
```

Po reboot ponownie `nvidia-smi` — dopóki nie pokaże GPU, nic dalej nie ma
sensu robić.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8000/tcp    # port ocr-api, chroniony przez API_KEY
sudo ufw enable
sudo ufw status
```

## 2. uv, Python 3.13, repo

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

git clone <adres-repo> o2j-lab && cd o2j-lab
uv python install 3.13
uv sync --extra gpu --extra serve --extra lab
```

## 3. llama.cpp z CUDA — serwer modelu do ekstrakcji JSON (`qwen3-8b-l4`)

`lab serve` (`src/lab/llm/server.py`) woła binarkę `llama-server` z `PATH` —
to nie jest zależność z `pyproject.toml`, trzeba ją zbudować z CUDA:

```bash
sudo apt install -y build-essential cmake git nvidia-cuda-toolkit
nvcc --version    # musi działać

git clone https://github.com/ggml-org/llama.cpp /opt/llama.cpp
cd /opt/llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j"$(nproc)" --target llama-server

sudo ln -s /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
llama-server --version
```

Start przez `lab` (pobiera model z HF przy pierwszym starcie, patrz profil
`qwen3-8b-l4` w `configs/models.yaml`: `-ngl 99 -fa on`, port 8082):

```bash
cd ~/o2j-lab
tmux new -s llm
uv run lab serve --model qwen3-8b-l4
# Ctrl-B D, żeby odpiąć tmux bez zabijania serwera
```

Sprawdzenie na samym serwerze:

```bash
curl http://localhost:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b-l4","messages":[{"role":"user","content":"Powiedz jedno zdanie po polsku. /no_think"}],"temperature":0}'
```

Upewnij się, że `.env` na serwerze ma ustawiony `API_KEY` (dowolny sekret —
`python3 -c "from ocr_api.keygen import generate_key; print(generate_key())"`).

## 4. Start serwerów (GPU box)

```bash
cd ~/o2j-lab
tmux new -s gpu
bash scripts/gpu-server-bootstrap.sh
# Ctrl-B D, żeby odpiąć tmux bez zabijania serwerów
```

Skrypt startuje `lab serve --model qwen3-8b-l4` (port 8082, tylko localhost)
i `ocr-api serve --host 0.0.0.0 --port 8000` (OCR obrazowy, model
`lightonai/LightOnOCR-3-0.8B` na CUDA), czeka aż `/health` odpowie, wykrywa
publiczny adres **IPv4** (`curl -4`) i na końcu drukuje gotowe komendy do
wklejenia na klienta. Endpoint jest zawsze `http://`, nigdy `https://`.

Bootstrap ustawia `OCR_FORCE_IMAGE=1`, więc OCR zawsze renderuje stronę do
obrazu i używa modelu CUDA — nawet gdy PDF ma warstwę tekstową. Aby przywrócić
szybką ścieżkę `pdfplumber`, uruchom:

```bash
OCR_FORCE_IMAGE=0 bash scripts/gpu-server-bootstrap.sh
```

```
=== terminal 1 — backend (na kliencie): =============================
bash scripts/connect-gpu-backend.sh <public-ip>:8000 <API_KEY> <BACKEND_API_TOKEN>

=== terminal 2 — frontend (na kliencie): ============================
bash scripts/connect-gpu-frontend.sh <BACKEND_API_TOKEN>
=====================================================================
```

Skrypt generuje `BACKEND_API_TOKEN` poleceniem `openssl rand -hex 32` i
wypisuje go osobno. `API_KEY` chroni serwis OCR na L4; `BACKEND_API_TOKEN`
chroni lokalny backend i jest przekazywany do Vite jako `O2J_API_TOKEN`.

## 5. Połączenie z własnej maszyny (klient)

Terminal 1 — backend:

```bash
bash scripts/connect-gpu-backend.sh <public-ip>:8000 <API_KEY> <BACKEND_API_TOKEN>
```

Terminal 2 — frontend:

```bash
bash scripts/connect-gpu-frontend.sh <BACKEND_API_TOKEN>
```

Backend ustawia `WEB_OCR_BACKEND=remote`, `OCR_SERVICE_URL`, `OCR_SERVICE_KEY`
i `API_TOKEN`. Frontend ustawia `O2J_API_TOKEN` i `O2J_API_TARGET`. Cały OCR+LLM idzie
przez `POST /analyze` na serwer GPU z nagłówkiem `X-API-Key`.

Weryfikacja bez uruchamiania backendu:

```bash
curl http://<public-ip>:8000/health
curl http://<public-ip>:8000/analyze -H "X-API-Key: <API_KEY>" -F file=@test.pdf
```

## Rozwiązywanie problemów

| Problem | Przyczyna |
|---|---|
| `nvidia-smi: command not found` | sterownik nie zainstalowany — krok 1 |
| `llama-server not found in PATH` | nie zbudowano/nie zlinkowano binarki — krok 3 |
| `ensure_server` wisi >900s | pobieranie modelu z HF trwa długo przy pierwszym starcie; sprawdź `work/servers/qwen3-8b-l4.log` |
| `gpu-server-bootstrap.sh` nie drukuje komendy klienta | `ocr-api` nie wstał — sprawdź logi w tmux, `curl localhost:8000/health` |
| klient dostaje 401/403 | `API_KEY` na serwerze ≠ `OCR_SERVICE_KEY` na kliencie |
