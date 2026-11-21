# OCR LLM serving path — short design

> **ARCHIVED 2026-11-21 — historical only.** Describes the removed
> `OCR_BACKEND=llama_cpp` path and deleted files (`src/lab/serve.py`,
> `Dockerfile`, root `requirements.txt`). Current services: `ocr-api` (CUDA)
> and `local-ai` (MLX), with prebuilt 8-bit MLX weights downloaded by
> `scripts/make-mlx-model.sh`. Pages render at 400 DPI, longest edge 2048 px.

## Intent

Judges hit one HTTP API over the network with an API key. The Mac runs the
demo fast on Apple Metal. The same code must also run CPU-only for the target
deployment story. Both paths use exactly `lightonai/LightOnOCR-3-4B` in full
BF16, no quantized weights.

## Goals

- One FastAPI server, `OCR_BACKEND` picks the backend: `mlx` or `llama_cpp`.
- Same `extract_page(image) -> str` interface for both backends.
- API key auth, serialized inference, single worker.
- Scanned PDFs only: render pages to images, no text-layer extraction.

## Non-goals

- No classification, extraction to JSON, or PDF text shortcut.
- No other model, no quantized checkpoints.
- No changes to the existing `lab` CLI or `o2jcore`.

## Constraints and decisions

- **Model:** `lightonai/LightOnOCR-3-4B` for both backends. mlx-vlm loads the
  HF repo directly in BF16. For `llama_cpp`, no BF16 GGUF is published, so the
  CPU path converts the same BF16 safetensors to a BF16 GGUF once with
  `convert_hf_to_gguf.py --outtype bf16` and uses the published F16 mmproj.
  Projector is not the LLM weights, so this is not a language-model quant.
  **Needs confirmation:** accept this one-time local conversion, since
  "BF16 + no quants + llama_cpp" is otherwise unavailable today.
- **PDF rendering:** `pypdfium2` (already a dependency). No PyMuPDF — `AI/PLAN.md`
  bans AGPL. No `fitz`, no text extraction.
- **Prompt:** empty prompt gives full-page markdown transcription; `"grounding"`
  gives coordinates. API uses empty prompt.
- **Concurrency:** one `asyncio.Lock` around inference; `uvicorn --workers 1`.
- **CPU server:** separate `llama-server` process, `-ngl 0`, OpenAI-compatible
  `/v1/chat/completions` with image_url data URI. No Python `llama-cpp-python`
  dependency needed.

## Approach

One sensible way: a backend interface with two implementations behind one
FastAPI app. Alternatives rejected: two separate apps (duplicates auth and
routing), or a single backend with runtime model swap (breaks "always works"
CPU story and the two-model-loaded memory budget).

## Files

- `src/lab/serve.py` — FastAPI app, key check, PDF render, lock, backend
  interface + `mlx` and `llama_cpp` implementations.
- `pyproject.toml` — add `serve` extra (`fastapi`, `uvicorn`,
  `python-multipart`) and `demo` extra (`mlx-vlm`).
- `requirements.txt` / `uv.lock` — refresh after dependency change.
- `Dockerfile` — CPU image, defaults `OCR_BACKEND=llama_cpp`.
- `docs/LICENSES.md` — add FastAPI, uvicorn, mlx-vlm, LightOnOCR-3-4B.
- `tests/test_serve.py` — key rejection, page rendering + mocked backend,
  lock serialization.
- `README.md` — run commands for both backends, ngrok-free cloudflared hint,
  `caffeinate -dims`.

## API contract

`POST /analyze`, header `X-API-Key`, multipart `file` (PDF):
`{"backend": "mlx", "pages": [{"page": 1, "text": "..."}]}`.
`GET /health` returns backend and model id, no auth.

## Left to builder

Nothing open besides the BF16 GGUF conversion confirmation above.
