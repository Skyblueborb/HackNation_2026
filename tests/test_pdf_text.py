"""Tests for o2jcore.text.pdf_text: extract_pages and has_text_layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab import paths
from o2jcore.text.pdf_text import PageText, extract_pages, has_text_layer

DATA_ROOT = paths.data_root()
DANE = DATA_ROOT / "dane"

SCAN_ONLY_PDF = (
    DATA_ROOT
    / "szablon-aplikacja"
    / "input"
    / "case1"
    / "przyklad odwolanie.pdf"
)


@pytest.mark.parametrize("extractor", ["pdfium", "pdfplumber", "pdfplumber_layout"])
def test_extract_pages_single_page_przelew(extractor: str) -> None:
    pdf_path = DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    pages = extract_pages(pdf_path, extractor)

    assert len(pages) == 1
    page = pages[0]
    assert isinstance(page, PageText)
    assert page.n == 1
    assert page.text.strip() != ""
    # From przyklad_01/przelew.json: na_rachunek starts with 684382230...
    # and the document is titled "POLECENIE PRZELEWU".
    normalized = page.text.replace(" ", "").replace("\n", "").replace("\r", "")
    assert "684382230" in normalized
    assert page.width > 0
    assert page.height > 0


@pytest.mark.parametrize("extractor", ["pdfium", "pdfplumber", "pdfplumber_layout"])
def test_extract_pages_multipage_odwolanie(extractor: str) -> None:
    pdf_path = DANE / "przyklad_45" / "odwolanie.pdf"
    pages = extract_pages(pdf_path, extractor)

    assert len(pages) == 11
    for i, page in enumerate(pages, start=1):
        assert page.n == i
    # Sequential and 1-indexed.
    assert [p.n for p in pages] == list(range(1, 12))


def test_extract_pages_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        extract_pages(Path("/nonexistent/path/does-not-exist.pdf"), "pdfium")


def test_has_text_layer_true_for_sample_of_training_pdfs() -> None:
    samples = [
        DANE / "przyklad_01" / "odwolanie.pdf",
        DANE / "przyklad_01" / "pelnomocnictwo.pdf",
        DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf",
        DANE / "przyklad_10" / "odwolanie.pdf",
        DANE / "przyklad_10" / "pelnomocnictwo.pdf",
        DANE / "przyklad_10" / "potwierdzenie_przelewu.pdf",
        DANE / "przyklad_30" / "odwolanie.pdf",
        DANE / "przyklad_45" / "odwolanie.pdf",
        DANE / "przyklad_50" / "pelnomocnictwo.pdf",
        DANE / "przyklad_60" / "potwierdzenie_przelewu.pdf",
    ]
    for pdf_path in samples:
        assert pdf_path.exists(), f"missing fixture {pdf_path}"
        assert has_text_layer(pdf_path) is True, f"expected text layer in {pdf_path}"


def test_has_text_layer_false_for_scan_only_pdf() -> None:
    assert SCAN_ONLY_PDF.exists(), f"missing scan-only fixture {SCAN_ONLY_PDF}"
    assert has_text_layer(SCAN_ONLY_PDF) is False
