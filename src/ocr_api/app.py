"""Production FastAPI app: CUDA OCR, optional LLM processor injected by config."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

from fastapi import Depends, FastAPI, File, UploadFile

from ocr_common import (
    configure_logging,
    load_llm_processor,
    run_ocr_async,
    verify_key,
)
from ocr_common.common import logger
from ocr_api.backends import ATTN_IMPL, CudaBackend, MODEL_ID, cuda_session

PRELOAD = os.environ.get("OCR_PRELOAD", "1") == "1"
PROCESSOR = load_llm_processor(os.environ.get("OCR_LLM_PROCESSOR"))
configure_logging(verbose=os.environ.get("OCR_VERBOSE", "0") == "1")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "starting: backend=cuda model=%s dtype=bf16 attn=%s preload=%s llm=%s",
        MODEL_ID,
        ATTN_IMPL,
        PRELOAD,
        type(PROCESSOR).__name__ if PROCESSOR else "none",
    )
    if PRELOAD:
        started = time.perf_counter()
        logger.info("loading CUDA model ...")
        await asyncio.to_thread(cuda_session)
        logger.info("model ready in %.1fs", time.perf_counter() - started)
    yield
    logger.info("shutting down")


app = FastAPI(title="OCR LLM API (CUDA)", lifespan=lifespan)
_backend = None


def get_backend() -> CudaBackend:
    global _backend
    if _backend is None:
        _backend = CudaBackend()
    return _backend


@app.get("/health")
def health() -> dict:
    return {"backend": "cuda", "model": MODEL_ID}


@app.post("/analyze", dependencies=[Depends(verify_key)])
async def analyze(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    return await run_ocr_async(
        data,
        get_backend(),
        backend="cuda",
        model=MODEL_ID,
        processor=PROCESSOR,
        filename=file.filename,
    )
