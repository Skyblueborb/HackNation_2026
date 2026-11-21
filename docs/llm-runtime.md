# LLM runtime

Two ways to run the same `lab.llm` server stack. Both use a profile from
`configs/models.yaml` and the OpenAI-compatible endpoint `http://localhost:<port>/v1`.

## Production — NVIDIA L4 (Ubuntu Noble)

Profile `qwen3-8b-l4`: full GPU offload (`-ngl 99`) and flash attention
(`-fa on`). Its port, HF repo and server flags live in `configs/models.yaml`.

```bash
lab serve --model qwen3-8b-l4
```

`lab serve` calls `ensure_server`, prints the server command and log path, then
blocks until Ctrl-C, which calls `stop_server`. The same profile is used by
sweeps and the OCR API when selected via `OCR_LLM_MODEL`.

## Local — Mac Metal (and anywhere else)

Profile `local-llm`: Qwen3-4B GGUF with Metal GPU offload. Port and flags come
from `configs/models.yaml`. Wrapped by the `local-llm` CLI, which contains no
LLM logic — it only drives `lab.llm.server`.

```bash
python -m local_ai.llm serve                 # profile local-llm, Metal
python -m local_ai.llm serve --model local-llm
python -m local_ai.llm serve --cpu           # CPU fallback: -ngl 0
python -m local_ai.llm serve --port 8090     # override port + base_url
```

`local-llm serve` prints the OpenAI-compatible endpoint and the model id to
send in requests, then blocks until Ctrl-C before stopping the server.
`--cpu` keeps the other flags (`-c 8192 --jinja --parallel 1`) and only changes
`-ngl` to `0`. `--port N` sets both `port` and `base_url` to
`http://localhost:N/v1`. Both flags compose.

The equivalent `lab` command is available too:

```bash
lab serve --model local-llm
```

## Selecting the model for the OCR API

`ocr_api.app` reads two environment variables, via `ocr_common.registry`:

- `OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor` loads the LLM bridge.
- `OCR_LLM_MODEL=<profile id>` picks the key in `configs/models.yaml`. It
  defaults to `qwen3-8b` when unset.

Point `OCR_LLM_MODEL` at the profile whose server you started:

```bash
# Production: full GPU offload + flash attention on the L4 box
OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor OCR_LLM_MODEL=qwen3-8b-l4 ocr-api serve

# Local: start `local-llm serve` first, then
OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor OCR_LLM_MODEL=local-llm ocr-api serve
```

The bridge builds its client from the same profile, so model id, base_url,
`no_think_suffix` and `structured_output` stay consistent with the server.
See `docs/llm-module-contract.md` for the processor contract.

## One server at a time

`ensure_server` reuses an already-healthy server and returns `None` in that
case. Work with only one profile at a time; the CLI stops only the process it
started. Logs go to `<work_root>/servers/<model-id>.log`.
