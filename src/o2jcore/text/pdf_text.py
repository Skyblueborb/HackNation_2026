"""Backend-agnostic PDF text extraction.

Three extractors are supported, all free of AGPL-licensed dependencies
(no PyMuPDF/fitz anywhere):

- 'pdfium': pypdfium2 (fastest, used for the has_text_layer gate)
- 'pdfplumber': pdfplumber's default extract_text()
- 'pdfplumber_layout': pdfplumber's extract_text(layout=True)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Extractor = Literal["pdfium", "pdfplumber", "pdfplumber_layout"]

_VALID_EXTRACTORS = ("pdfium", "pdfplumber", "pdfplumber_layout")


@dataclass(frozen=True)
class PageText:
    n: int  # 1-indexed page number
    text: str
    width: float
    height: float


def _extract_pdfium(pdf_path: Path) -> list[PageText]:
    import pypdfium2 as pdfium

    pages: list[PageText] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                width, height = page.get_size()
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
            finally:
                page.close()
            pages.append(PageText(n=i + 1, text=text, width=float(width), height=float(height)))
    finally:
        pdf.close()
    return pages


def _extract_pdfplumber(pdf_path: Path, layout: bool) -> list[PageText]:
    import pdfplumber

    pages: list[PageText] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if layout:
                text = page.extract_text(layout=True) or ""
            else:
                text = page.extract_text() or ""
            pages.append(
                PageText(
                    n=i + 1,
                    text=text,
                    width=float(page.width),
                    height=float(page.height),
                )
            )
    return pages


def extract_pages(pdf_path: Path, extractor: Extractor) -> list[PageText]:
    """Extract per-page text using the named backend.

    Raises a clear exception (does not swallow) if the file can't be
    opened at all -- that's a different failure mode from "no text
    layer", which is not an error, just an empty/near-empty string.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if extractor not in _VALID_EXTRACTORS:
        raise ValueError(f"Unknown extractor {extractor!r}; must be one of {_VALID_EXTRACTORS}")

    if extractor == "pdfium":
        return _extract_pdfium(pdf_path)
    if extractor == "pdfplumber":
        return _extract_pdfplumber(pdf_path, layout=False)
    return _extract_pdfplumber(pdf_path, layout=True)


def has_text_layer(pdf_path: Path, min_chars: int = 50) -> bool:
    """True if the PDF has a usable text layer (the "needs OCR?" gate).

    Uses the 'pdfium' extractor only (fastest backend) and counts
    non-whitespace characters across all pages.
    """
    pages = extract_pages(pdf_path, "pdfium")
    total_non_whitespace = sum(len("".join(p.text.split())) for p in pages)
    return total_non_whitespace >= min_chars
