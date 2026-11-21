"""Tests for lab.cache: content-addressed extraction cache."""

from __future__ import annotations

from pathlib import Path

from lab import paths
from lab.cache import pdf_content_hash, read_cached, write_cache
from o2jcore.text.pdf_text import PageText, extract_pages

DANE = paths.data_root() / "dane"


def test_pdf_content_hash_deterministic() -> None:
    pdf_path = DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    h1 = pdf_content_hash(pdf_path)
    h2 = pdf_content_hash(pdf_path)
    assert h1 == h2
    assert len(h1) == 16


def test_pdf_content_hash_distinguishes_files() -> None:
    h1 = pdf_content_hash(DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf")
    h2 = pdf_content_hash(DANE / "przyklad_02" / "potwierdzenie_przelewu.pdf")
    assert h1 != h2


def test_write_then_read_cache_roundtrip(tmp_path: Path) -> None:
    pdf_path = DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    pages = extract_pages(pdf_path, "pdfium")

    cache_root = tmp_path / "cache"
    written_path = write_cache(cache_root, pdf_path, "pdfium", pages)
    assert written_path.exists()

    cached = read_cached(cache_root, pdf_path, "pdfium")
    assert cached is not None
    assert cached["meta"]["n_pages"] == len(pages)
    assert len(cached["pages"]) == len(pages)
    for original, roundtripped in zip(pages, cached["pages"]):
        assert roundtripped["n"] == original.n
        assert roundtripped["text"] == original.text


def test_read_cached_returns_none_on_cold_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    pdf_path = DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    assert read_cached(cache_root, pdf_path, "pdfium") is None


def test_ingest_subset_reports_hits_then_misses(tmp_path: Path) -> None:
    """Direct test of the cache functions driving the same logic as `lab ingest`:
    first pass over a small set of files is all misses, second pass (same
    cache dir) is all hits.
    """
    cache_root = tmp_path / "cache"
    extractor = "pdfplumber"
    pdf_paths = [
        DANE / "przyklad_01" / "odwolanie.pdf",
        DANE / "przyklad_01" / "pelnomocnictwo.pdf",
        DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf",
        DANE / "przyklad_02" / "odwolanie.pdf",
    ]

    def run_pass() -> tuple[int, int]:
        hits = 0
        misses = 0
        for pdf_path in pdf_paths:
            cached = read_cached(cache_root, pdf_path, extractor)
            if cached is not None:
                hits += 1
                continue
            pages = extract_pages(pdf_path, extractor)
            write_cache(cache_root, pdf_path, extractor, pages)
            misses += 1
        return hits, misses

    hits_1, misses_1 = run_pass()
    assert (hits_1, misses_1) == (0, len(pdf_paths))

    hits_2, misses_2 = run_pass()
    assert (hits_2, misses_2) == (len(pdf_paths), 0)


def test_read_write_with_precomputed_hash_do_not_rehash(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    digest = pdf_content_hash(pdf_path)
    calls: list[Path] = []

    def counting_hash(path):
        calls.append(Path(path))
        return pdf_content_hash(path)

    monkeypatch.setattr("lab.cache.pdf_content_hash", counting_hash)

    cache_root = tmp_path / "cache"
    pages = [PageText(n=1, text="hello", width=100, height=100)]
    assert read_cached(cache_root, pdf_path, "pdfium", content_hash=digest) is None
    write_cache(cache_root, pdf_path, "pdfium", pages, content_hash=digest)
    assert read_cached(cache_root, pdf_path, "pdfium", content_hash=digest) is not None

    assert calls == []
