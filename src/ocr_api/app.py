"""Production FastAPI app: CUDA OCR, optional LLM processor injected by config."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from ocr_common import (
    configure_logging,
    load_llm_processor,
    run_analyze_async,
    verify_key,
)
from ocr_common.common import get_api_key, logger
from ocr_api.backends import (
    ATTN_IMPL,
    CudaBackend,
    LlamaCppBackend,
    MODEL_ID,
    cuda_session,
    warmup,
)


def validate_startup() -> None:
    """Fail fast on config errors that would otherwise break the first request."""
    get_api_key()
    if os.environ.get("OCR_LLM_PROCESSOR"):
        from ocr_api.llm_processor import validate_model

        validate_model()


OCR_CPP_BACKEND = os.environ.get("OCR_CPP_BACKEND", "0") == "1"
PRELOAD = os.environ.get("OCR_PRELOAD", "1") == "1" and not OCR_CPP_BACKEND
MAX_UPLOAD_BYTES = int(os.environ.get("OCR_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
# Resolving this returns a proxy; the real processor is built in lifespan.
PROCESSOR = load_llm_processor(os.environ.get("OCR_LLM_PROCESSOR"))
configure_logging(verbose=os.environ.get("OCR_VERBOSE", "0") == "1")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_startup()
    if os.environ.get("OCR_LLM_PROCESSOR"):
        from ocr_api.llm_processor import get_processor

        get_processor()
    logger.info(
        "starting: backend=%s model=%s dtype=bf16 attn=%s preload=%s llm=%s",
        "llamacpp" if OCR_CPP_BACKEND else "cuda",
        MODEL_ID,
        ATTN_IMPL,
        PRELOAD,
        type(PROCESSOR).__name__ if PROCESSOR else "none",
    )
    if PRELOAD:
        started = time.perf_counter()
        logger.info("loading CUDA model ...")
        await asyncio.to_thread(cuda_session)
        await asyncio.to_thread(warmup)
        logger.info("model ready in %.1fs", time.perf_counter() - started)
    yield
    logger.info("shutting down")


app = FastAPI(title="OCR LLM API (CUDA)", lifespan=lifespan)
_backend = None


def get_backend() -> CudaBackend | LlamaCppBackend:
    global _backend
    if _backend is None:
        _backend = LlamaCppBackend() if OCR_CPP_BACKEND else CudaBackend()
    return _backend


@app.get("/health")
def health() -> dict:
    return {"backend": "cuda", "model": MODEL_ID}


@app.post("/analyze", dependencies=[Depends(verify_key)])
async def analyze(file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds the {MAX_UPLOAD_BYTES}-byte upload limit",
        )
    return await run_analyze_async(
        data,
        get_backend(),
        backend="cuda",
        model=MODEL_ID,
        processor=PROCESSOR,
        filename=file.filename,
    )
