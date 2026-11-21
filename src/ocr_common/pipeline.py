"""OCR pipeline shared by the production and local HTTP apps."""

from __future__ import annotations

import asyncio
import time

from ocr_common.common import image_is_blank, inference_lock, llm_semaphore, logger, render_pages
from ocr_common.ports import LLMProcessor, OCRDocument, OCRPage, PageExtractor


async def run_ocr_async(
    data: bytes,
    extractor: PageExtractor,
    *,
    backend: str,
    model: str,
    processor: LLMProcessor | None = None,
    filename: str | None = None,
) -> dict:
    """Render pages, extract text, then call an optional LLM processor.

    The inference lock covers rendering/generation only. The LLM HTTP call runs
    outside it, bounded by llm_semaphore, so OCR of the next request is not
    blocked while the current one waits on the LLM server.
    """
    started = time.perf_counter()
    logger.info("analyze start: backend=%s model=%s", backend, model)
    async with inference_lock:
        response, document = await asyncio.to_thread(
            _run_locked, data, extractor, backend, model, started, filename
        )
    if processor is not None:
        async with llm_semaphore:
            response["llm"] = await asyncio.to_thread(processor.process, document)
    logger.info(
        "analyze done: pages=%d total=%.2fs",
        len(document.pages),
        time.perf_counter() - started,
    )
    return response


def _run_locked(
    data: bytes,
    extractor: PageExtractor,
    backend: str,
    model: str,
    started: float,
    filename: str | None = None,
) -> tuple[dict, OCRDocument]:
    images = render_pages(data)
    logger.info("rendered %d page(s)", len(images))
    pages: list[OCRPage] = []
    for number, image in enumerate(images, start=1):
        page_started = time.perf_counter()
        blank = image_is_blank(image)
        logger.info("page %d: size=%s blank=%s", number, image.size, blank)
        text = extractor.extract_page(image).strip()
        logger.info(
            "page %d: %d chars in %.2fs",
            number,
            len(text),
            time.perf_counter() - page_started,
        )
        if not text:
            logger.warning("page %d: OCR returned empty text", number)
        pages.append(OCRPage(number=number, text=text))

    document = OCRDocument(
        backend=backend, model=model, pages=tuple(pages), filename=filename
    )
    return document.as_dict(), document
