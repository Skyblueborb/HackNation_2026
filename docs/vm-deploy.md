# Wdrożenie na VM-ce organizatora (Ubuntu 24.04, 2 vCPU, bez GPU)

Wymagania organizatora: całość w `/opt/solution`, `RUN.md` z jedną
nieinteraktywną komendą, `input/` → `output/`, usługi w tle wstają po
restarcie. Parametry maszyny i zasady oceny: `VM.md` w repo konkursowym.

Podział pracy: **tekst i klasyfikacja lokalnie na VM-ce** (pdfplumber, bez
GPU, milisekundy na stronę), **LLM na wynajętym serwerze NVIDIA** po API.
Lokalny `llama-server` na 2 vCPU nie zmieściłby się w limicie 45 minut na 150
plików. Postawienie serwera GPU: `docs/gpu-server/README.md`.

## 1. Kod w `/opt/solution`

```bash
cd /opt/solution
git clone <adres-repo> .          # katalog należy do Waszego konta, bez sudo
cp .env.example .env              # API_TOKEN, API_KEY (GUI); OCR_LLM_MODEL
```

`input/` i `output/` już istnieją — nie usuwać, nie zmieniać nazw.

## 2. Tunel SSH do serwera GPU jako usługa

`configs/models.yaml` trzyma `base_url: http://localhost:8082/v1`, więc tunel
jest całą integracją — zero zmian w kodzie. `llama-server` nie ma autoryzacji,
dlatego **nigdy** nie wystawiamy portu 8082 publicznie; tunel zamiast tego.

Klucz SSH dla roota (usługa startuje przed logowaniem użytkownika):

```bash
sudo ssh-keygen -t ed25519 -f /root/.ssh/o2j-gpu -N ''
sudo cat /root/.ssh/o2j-gpu.pub        # dopisać do ~/.ssh/authorized_keys na serwerze GPU
sudo ssh -i /root/.ssh/o2j-gpu <user>@<gpu-host> true   # raz, żeby przyjąć host key
```

```bash
sudo tee /etc/systemd/system/o2j-llm-tunnel.service >/dev/null <<'EOF'
[Unit]
Description=SSH tunnel to the GPU LLM server (localhost:8082)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/ssh -N -T \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new -i /root/.ssh/o2j-gpu \
  -L 8082:localhost:8082 <user>@<gpu-host>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now o2j-llm-tunnel
curl -s http://localhost:8082/health      # musi odpowiedzieć
```

Po stronie serwera GPU `llama-server` musi startować sam po restarcie —
`scripts/gpu-server-bootstrap.sh` (patrz `docs/gpu-server/README.md`) startuje
go pod `tmux`, ale to nie przeżyje restartu bez `systemctl enable` na usłudze,
która go woła — inaczej tunel będzie żył, a model nie.

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
docker compose up -d        # http://<adres-ip>:3000, restart: unless-stopped
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
systemctl is-active o2j-llm-tunnel     # active
curl -s http://localhost:8082/health
sudo docker compose --profile batch run --rm batch
```

## Rozwiązywanie problemów

| Objaw | Przyczyna |
|---|---|
| wszystkie JSON-y puste (`{}`) | LLM nieosiągalny — `systemctl status o2j-llm-tunnel`, `curl localhost:8082/health` |
| `[fail] ...: Connection refused` | tunel żyje, ale `llama-server` na GPU nie działa |
| `unknown OCR_LLM_MODEL profile` | `OCR_LLM_MODEL` w `.env` nie pasuje do klucza w `configs/models.yaml` |
| wsad nie widzi plików | repo nie jest w `/opt/solution` (montaże `./input`, `./output` są względne do pliku compose) |
| GUI nie odpowiada z internetu | otwarte są porty 80/443/8000/8080 — port 3000 trzeba przemapować |
