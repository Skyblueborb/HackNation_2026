# Postawienie serwerów na wynajętym GPU (Ubuntu 24.04 LTS, NVIDIA L4)

Dokładna, skopiuj-wklej instrukcja na świeżym Ubuntu 24.04 z kartą NVIDIA
(L4, 24 GB VRAM — profil `qwen3-8b-l4` w `configs/models.yaml` jest dobrany
pod ten GPU). Kontekst architektury: `docs/superpowers/specs/2026-11-21-cloud-gpu-split-design.md`.
Jak się z tym łączyć z własnej maszyny (tunel SSH, zero zmian w kodzie):
`docs/llm-runtime.md#remote-gpu-box--ssh-tunnel-no-code-changes`.

Zasada bezpieczeństwa obowiązująca przez całą instrukcję: **na firewallu
publicznie otwarty jest tylko port 22.** `llama-server` (8082) nie ma żadnej
autoryzacji — nigdy nie wystawiaj go na świat.

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
sudo ufw enable
sudo ufw status    # powinno pokazać tylko 22/tcp
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

## 4. `ocr_api` — OCR obrazowy na GPU (opcjonalnie)

Potrzebne tylko gdy demo musi czytać skany bez warstwy tekstowej (model
wizyjny `lightonai/LightOnOCR-3-4B` na CUDA). Dla samego zbioru konkursowego
zwykle wystarcza `WEB_OCR_BACKEND=text` (warstwa tekstowa PDF-a, bez GPU) —
pomiń tę sekcję, jeśli o to idzie.

```bash
sudo apt install -y docker.io
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

cd ~/o2j-lab
docker build -t ocr-api -f Dockerfile.gpu .

python3 -c "from ocr_api.keygen import generate_key; print(generate_key())"
# zapisz wygenerowany klucz jako <API_KEY> niżej

docker run -d --name ocr-api --restart unless-stopped \
  --gpus all --network host \
  -e API_KEY=<API_KEY> \
  -e OCR_MODEL=lightonai/LightOnOCR-3-4B \
  -e OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor \
  -e OCR_LLM_MODEL=qwen3-8b-l4 \
  ocr-api
```

`OCR_MODEL` wybiera wagi OCR. Domyślnie jest to
`lightonai/LightOnOCR-3-4B` (BF16 na CUDA). `0.8B` z `models/` jest w formacie
MLX i działa tylko przez `local-ai serve` na Macu — nie przez `ocr-api serve`.
Aby użyć 0.8B na L4, potrzebny jest transformers-compatible checkpoint CUDA.

`--network host` jest wymagany: `ocr_api` woła LLM-bridge po
`http://localhost:8082/v1`, więc musi widzieć ten sam `localhost` co serwer
z kroku 3.

Sprawdzenie na serwerze:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/analyze -H "X-API-Key: <API_KEY>" -F file=@test.pdf
```

## 5. Połączenie z własnej maszyny

```bash
ssh -N -L 8082:localhost:8082 -L 8000:localhost:8000 \
    -o ServerAliveInterval=30 <user>@<gpu-host>
```

Zostaw to działające w jednym terminalu (albo jako usługę w tle). Z
otwartym tunelem `http://localhost:8082` i `http://localhost:8000` na Twojej
maszynie to serwer GPU — cała istniejąca konfiguracja projektu
(`OCR_LLM_MODEL=qwen3-8b-l4` w `.env`, `lab run`/`lab predict-one`/`lab sweep`,
`backend/main.py`) działa bez żadnych zmian w kodzie.

Weryfikacja z laptopa (po otwarciu tunelu):

```bash
curl http://localhost:8082/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen3-8b-l4","messages":[{"role":"user","content":"test /no_think"}],"temperature":0}'
```

## Rozwiązywanie problemów

| Problem | Przyczyna |
|---|---|
| `nvidia-smi: command not found` | sterownik nie zainstalowany — krok 1 |
| `llama-server not found in PATH` | nie zbudowano/nie zlinkowano binarki — krok 3 |
| `ensure_server` wisi >900s | pobieranie modelu z HF trwa długo przy pierwszym starcie; sprawdź `work/servers/qwen3-8b-l4.log` |
| `docker run --gpus all` błąd `unknown flag` | `nvidia-container-toolkit` nie skonfigurowany — krok 4 |
| Tunel się rozłącza | dodaj `-o ServerAliveInterval=30 -o ServerAliveCountMax=3`, albo `autossh` |
