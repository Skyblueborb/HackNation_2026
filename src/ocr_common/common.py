import asyncio
import logging
import os
import secrets

import pypdfium2
from fastapi import Header, HTTPException
from PIL import Image

logger = logging.getLogger("ocr")
inference_lock = asyncio.Lock()

MAX_EDGE = int(os.environ.get("OCR_MAX_EDGE", "2048"))

# Kept for backwards compatibility. Resolve the live value in get_api_key().
API_KEY = os.environ.get("API_KEY")


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
    """Render PDF pages at model size. No text layer is read."""
    if max_edge is None:
        max_edge = MAX_EDGE
    images = []
    with pypdfium2.PdfDocument(data) as pdf:
        for page in pdf:
            image = page.render(scale=dpi / 72).to_pil()
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
