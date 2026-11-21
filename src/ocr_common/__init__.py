"""Shared HTTP, PDF and pipeline contracts for the OCR services."""

from .common import (
    configure_logging,
    image_is_blank,
    inference_lock,
    llm_semaphore,
    render_pages,
    verify_key,
)
from .pipeline import run_ocr_async
from .ports import LLMProcessor, OCRDocument, OCRPage, PageExtractor
from .registry import load_llm_processor

__all__ = [
    "LLMProcessor",
    "OCRDocument",
    "OCRPage",
    "PageExtractor",
    "configure_logging",
    "image_is_blank",
    "inference_lock",
    "llm_semaphore",
    "load_llm_processor",
    "render_pages",
    "run_ocr_async",
    "verify_key",
]
