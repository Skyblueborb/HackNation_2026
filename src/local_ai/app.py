"""Local FastAPI app: MLX OCR, optional LLM processor injected by config."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from PIL import Image

from ocr_common import (
    configure_logging,
    load_llm_processor,
    run_ocr_async,
    verify_key,
)
from ocr_common.common import get_api_key, logger


def validate_startup() -> None:
    """Fail fast on config errors that would otherwise break the first request."""
    get_api_key()
    if os.environ.get("OCR_LLM_PROCESSOR"):
        from ocr_api.llm_processor import validate_model

        validate_model()


MODEL_ID = os.environ.get("OCR_MODEL", "prithivMLmods/LightOnOCR-3-4B-MLX")
MAX_TOKENS = int(os.environ.get("OCR_MAX_TOKENS", "2048"))
# LightOnOCR-3: "" = full-page transcription; "grounding" = bounding boxes only.
PROMPT = os.environ.get("OCR_PROMPT", "")
PRELOAD = os.environ.get("OCR_PRELOAD", "1") == "1"
MLX_MODEL = os.environ.get("MLX_MODEL", "models/LightOnOCR-3-4B-mlx-8bit")
MAX_UPLOAD_BYTES = int(os.environ.get("OCR_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
# Resolving this returns a proxy; the real processor is built in lifespan.
PROCESSOR = load_llm_processor(os.environ.get("OCR_LLM_PROCESSOR"))
configure_logging(verbose=os.environ.get("OCR_VERBOSE", "0") == "1")

apply_chat_template = None
generate = None
load = None
load_config = None
_session = None
_session_path = None


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_startup()
    if os.environ.get("OCR_LLM_PROCESSOR"):
        from ocr_api.llm_processor import get_processor

        get_processor()
    logger.info(
        "starting: backend=mlx model=%s preload=%s llm=%s",
        MLX_MODEL,
        PRELOAD,
        type(PROCESSOR).__name__ if PROCESSOR else "none",
    )
    if PRELOAD:
        started = time.perf_counter()
        logger.info("loading MLX model ...")
        await asyncio.to_thread(mlx_session)
        logger.info("model ready in %.1fs", time.perf_counter() - started)
    yield
    logger.info("shutting down")


app = FastAPI(title="Local OCR LLM (MLX)", lifespan=lifespan)
_backend = None


def mlx_session(model_path: str | None = None):
    global _session, _session_path, apply_chat_template, generate, load, load_config
    path = model_path or MLX_MODEL
    if _session is None or _session_path != path:
        if load is None:
            from mlx_vlm import generate as _generate
            from mlx_vlm import load as _load
            from mlx_vlm.prompt_utils import apply_chat_template as _apply
            from mlx_vlm.utils import load_config as _load_config

            apply_chat_template = _apply
            generate = _generate
            load = _load
            load_config = _load_config
        model, processor = load(path)
        _session = (model, processor, load_config(path))
        _session_path = path
    return _session


class MlxBackend:
    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path

    def extract_page(self, image: Image.Image) -> str:
        model, processor, config = mlx_session(self.model_path)
        prompt = apply_chat_template(
            processor, config, PROMPT, num_images=1, enable_thinking=False
        )
        result = generate(
            model,
            processor,
            prompt,
            image=[image],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
        )
        text = str(getattr(result, "text", result)).strip()
        return re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def get_backend() -> MlxBackend:
    global _backend
    if _backend is None:
        _backend = MlxBackend()
    return _backend


@app.get("/health")
def health() -> dict:
    return {"backend": "mlx", "model": MODEL_ID}


@app.post("/analyze", dependencies=[Depends(verify_key)])
async def analyze(file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the {MAX_UPLOAD_BYTES}-byte upload limit",
        )
    return await run_ocr_async(
        data,
        get_backend(),
        backend="mlx",
        model=MODEL_ID,
        processor=PROCESSOR,
        filename=file.filename,
    )
