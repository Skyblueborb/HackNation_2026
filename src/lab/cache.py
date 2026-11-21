"""Content-addressed disk cache for PDF text-extraction results.

Keyed by sha256(pdf_bytes)[:16] + the extractor name.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from o2jcore.text.pdf_text import PageText


def pdf_content_hash(pdf_path: Path) -> str:
    """sha256 of the raw file bytes, hex, truncated to 16 chars."""
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    return digest[:16]


def cache_path(cache_root: Path, content_hash: str, variant: str) -> Path:
    return Path(cache_root) / content_hash / f"{variant}.json"


def read_cached(
    cache_root: Path, pdf_path: Path, extractor: str, *, content_hash: str | None = None
) -> dict | None:
    """Return the cached {'pages': [...], 'meta': {...}} dict, or None.

    `content_hash` may be supplied by a caller that already hashed the PDF
    (e.g. an ingest pass doing read-then-write) so the bytes are read once.
    """
    if content_hash is None:
        content_hash = pdf_content_hash(pdf_path)
    path = cache_path(cache_root, content_hash, extractor)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_cache(
    cache_root: Path,
    pdf_path: Path,
    extractor: str,
    pages: list[PageText],
    *,
    content_hash: str | None = None,
) -> Path:
    """Serialize pages + meta to the cache location, returning the path written."""
    if content_hash is None:
        content_hash = pdf_content_hash(pdf_path)
    path = cache_path(cache_root, content_hash, extractor)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "pages": [
            {"n": p.n, "text": p.text, "width": p.width, "height": p.height} for p in pages
        ],
        "meta": {
            "pdf_path": str(pdf_path),
            "extractor": extractor,
            "n_pages": len(pages),
        },
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
