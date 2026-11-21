"""Shared HTTP, PDF and pipeline contracts for the OCR services."""

from .common import (
    API_KEY,
    configure_logging,
    image_is_blank,
    inference_lock,
    render_pages,
    verify_key,
)
from .pipeline import run_ocr_async
from .ports import LLMProcessor, OCRDocument, OCRPage, PageExtractor
from .registry import load_llm_processor

__all__ = [
    "API_KEY",
    "LLMProcessor",
    "OCRDocument",
    "OCRPage",
    "PageExtractor",
    "configure_logging",
    "image_is_blank",
    "inference_lock",
    "load_llm_processor",
    "render_pages",
    "run_ocr_async",
    "verify_key",
]
