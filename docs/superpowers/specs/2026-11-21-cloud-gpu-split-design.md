# Cloud GPU / local AI split — short design

## Intent

Production runs on a rented NVIDIA L4 (Ubuntu Noble) box with PyTorch CUDA.
Local MLX code stays only for developer testing on the Mac. The two must not
share imports or dependencies.

## Goals

- `ocr_api`: production FastAPI app, CUDA backend only, same `/analyze` contract.
- `local_ai`: separate FastAPI app and package, MLX backend only, Mac-only.
- `ocr_common`: shared PDF rendering, API key check, inference lock, response shape.
- Production image installs no mlx-vlm; local install installs no CUDA extras.

## Non-goals

- No llama.cpp, GGUF, or vLLM in this step.
- No backend switch inside the production app.
- No change to the API response shape.

## Constraints

- Same request: `POST /analyze`, `X-API-Key`, multipart PDF; `GET /health`.
- Model: `lightonai/LightOnOCR-3-4B` full weights on CUDA, preloaded at startup.
- L4 has 24 GB VRAM; BF16 fits. Optional int8 via bitsandbytes is a follow-up,
  not part of this change.
- Uvicorn `--workers 1`; one `asyncio.Lock` around inference.
- Page render: 400 DPI, longest edge 2048 px. The shipped default prompt is
  `""` (plain transcription); `OCR_PROMPT=grounding` is opt-in for bounding boxes.

## Approaches

1. **Two packages + shared common (chosen).** Production image imports only
   `ocr_api` and `ocr_common`; local app imports only `local_ai` and
   `ocr_common`. Clean dependency boundary, small duplication of entrypoints.
2. One app with `OCR_BACKEND=cuda|mlx`. Rejected: local MLX dependency leaks into
   production image and vice versa.
3. Separate repositories. Rejected: too much churn for one team.

## Files

- `src/ocr_common/` — `render_pages`, `verify_key`, `inference_lock`, schemas.
- `src/ocr_api/` — `app.py`, `backends/cuda.py`, `__main__.py`.
- `src/local_ai/` — `app.py`, `backends/mlx.py`, `__main__.py`.
- `pyproject.toml` — extras: `gpu` (torch, torchvision, transformers),
  `local` (mlx-vlm), `serve` (fastapi, uvicorn, python-multipart).
- `Dockerfile.gpu` — Ubuntu Noble + CUDA runtime, installs `gpu` and `serve`.
- `tests/test_common.py`, `tests/test_cuda.py`, `tests/test_local_ai.py`.
- `README.md` — separate run instructions for GPU box and Mac.

## Left to builder

Nothing open besides the explicit choice of BF16 on CUDA.
