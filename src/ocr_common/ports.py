"""Stable contracts between OCR, the HTTP layer, and future LLM modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image


@dataclass(frozen=True)
class OCRPage:
    number: int
    text: str


@dataclass(frozen=True)
class OCRDocument:
    backend: str
    model: str
    pages: tuple[OCRPage, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "pages": [{"page": p.number, "text": p.text} for p in self.pages],
        }


class PageExtractor(Protocol):
    """Implement this to add a new OCR engine."""

    def extract_page(self, image: Image.Image) -> str: ...


class LLMProcessor(Protocol):
    """Implement this in the incoming LLM module.

    It receives the complete OCR result and returns any JSON-serializable value.
    The HTTP layer adds it as the `llm` field. No OCR class is required here.
    """

    def process(self, document: OCRDocument) -> Any: ...
