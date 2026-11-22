"""Text-layer "OCR" backend: read the PDF's own text instead of rendering it.

Every document in the competition data set ships a text layer, and the target
runtime is an office laptop with no GPU. For those inputs, rendering pages to
images and running a vision model is pure overhead: `pdfplumber` returns the
same characters in milliseconds and with no model weights on disk.

This module produces the same `OCRDocument` as `pipeline.run_ocr_async`, so the
LLM processor contract in `docs/llm-module-contract.md` is unchanged -- only the
way the page text is obtained differs. Use `has_text_layer()` from
`o2jcore.text.pdf_text` to decide which path an unknown PDF should take.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from ocr_common.ports import LLMProcessor, OCRDocument, OCRPage

# Matches the lab's default extractor, so API output and `lab run` metrics are
# produced from byte-identical page text. `layout=True` keeps the horizontal gap
# between side-by-side signature columns, which the flat extractor merged into
# one line and made mocodawca/pełnomocnik indistinguishable.
DEFAULT_EXTRACTOR = "pdfplumber_layout"


def extract_document(
    data: bytes,
    *,
    backend: str = "text",
    model: str = DEFAULT_EXTRACTOR,
    filename: str | None = None,
) -> OCRDocument:
    """Build an OCRDocument from a PDF's embedded text layer."""
    from o2jcore.text.pdf_text import extract_pages

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(data)
        pages = extract_pages(path, model)  # type: ignore[arg-type]

    return OCRDocument(
        backend=backend,
        model=model,
        pages=tuple(OCRPage(number=p.n, text=p.text.strip()) for p in pages),
        filename=filename,
    )


async def run_textlayer_async(
    data: bytes,
    *,
    backend: str = "text",
    model: str = DEFAULT_EXTRACTOR,
    processor: LLMProcessor | None = None,
    filename: str | None = None,
) -> dict:
    """Text-layer counterpart of `pipeline.run_ocr_async`.

    Returns the same response shape: `backend`, `pages`, and `llm` when a
    processor is configured. Extraction is CPU-cheap and holds no model, so it
    needs no inference lock. Only the LLM processor is serialized, via the
    shared llm_semaphore, so model calls never interleave.
    """
    from ocr_common.common import llm_semaphore, logger

    started = time.perf_counter()
    logger.info("analyze start: backend=%s model=%s (text layer)", backend, model)
    document = await asyncio.to_thread(
        extract_document, data, backend=backend, model=model, filename=filename
    )
    for page in document.pages:
        logger.info("page %d: %d chars", page.number, len(page.text))
        if not page.text:
            logger.warning("page %d: text layer is empty", page.number)

    response = document.as_dict()
    if processor is not None:
        async with llm_semaphore:
            response["llm"] = await asyncio.to_thread(processor.process, document)
    logger.info(
        "analyze done: pages=%d total=%.2fs",
        len(document.pages),
        time.perf_counter() - started,
    )
    return response
