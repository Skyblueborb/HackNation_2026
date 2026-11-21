import asyncio
import logging
import os
import secrets

import pypdfium2
from fastapi import Header, HTTPException
from PIL import Image

logger = logging.getLogger("ocr")

# One OCR model per process: serialize rendering/generation.
inference_lock = asyncio.Lock()
# One LLM server: bound concurrent LLM calls without blocking OCR. Default 1
# also serializes the LLM client's lazy init; raise with OCR_LLM_CONCURRENCY.
llm_semaphore = asyncio.Semaphore(int(os.environ.get("OCR_LLM_CONCURRENCY", "1")))

MAX_EDGE = int(os.environ.get("OCR_MAX_EDGE", "2048"))


def get_api_key() -> str:
    """Return the API key, raising only when a request actually needs it."""
    key = os.environ.get("API_KEY")
    if not key:
        raise RuntimeError("API_KEY must be set")
    return key


def configure_logging(verbose: bool = False) -> None:
    """Send structured logs to the console; --verbose enables DEBUG."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("ocr").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)


def render_pages(
    data: bytes, dpi: int = 400, max_edge: int | None = None
) -> list[Image.Image]:
    """Render PDF pages at a scale bounded by max_edge. No text layer is read.

    Rendering at a scale derived from max_edge avoids allocating full 400-DPI
    buffers for large pages only to shrink them afterwards.
    """
    if max_edge is None:
        max_edge = MAX_EDGE
    images = []
    with pypdfium2.PdfDocument(data) as pdf:
        for page in pdf:
            width, height = page.get_size()
            scale = min(dpi / 72, max_edge / max(width, height))
            image = page.render(scale=scale).to_pil()
            if max(image.size) > max_edge:
                image.thumbnail((max_edge, max_edge))
            images.append(image)
    return images


def image_is_blank(image: Image.Image) -> bool:
    """True when the rendered page is a single uniform color."""
    extrema = image.convert("L").getextrema()
    return extrema[0] == extrema[1]


def verify_key(x_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_api_key, get_api_key()):
        logger.warning("rejected request: invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")
