"""Deterministic preprocessing of extracted PDF text before it enters a prompt.

Fixes the classic cp1252/UTF-8 mojibake, removes repeated page footers,
normalizes Unicode, optionally trims very long documents, and derives
checksum-validated candidate values for the optional hint block.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from o2jcore.normalize.checksums import nip_valid, nrb_valid

_MOJIBAKE_RE = re.compile(r"Ã|Ä|Å|Â|â€|Å„|Å\x82")
_PAGE_FOOTER_RE = re.compile(
    r"^\s*[-–—\s]*(?:strona\s+\d+\s*(?:z|/)\s*\d+|page\s+\d+\s*(?:of|/)\s*\d+)[-–—\s]*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BLANK_RUN_RE = re.compile(r"\n{2,}")

_NIP_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
_NRB_RE = re.compile(r"(?<![\dA-Za-z])(?:PL\s*)?\d{2}(?:[\s-]?\d{4}){5}(?!\d)")
_DATE_RE = re.compile(r"(?<!\d)(\d{2}[./-]\d{2}[./-]\d{4})(?!\d)")
_MONEY_RE = re.compile(r"(?<!\w)(\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d{2})?|\d+[.,]\d{2})\s*(?:zł|PLN)\b", re.IGNORECASE)
_BZP_RE = re.compile(r"\b\d{4}/BZP\s*\d{8}(?:/\d{2})?(?!\d)", re.IGNORECASE)
_TED_RE = re.compile(r"\b(?:TED\s*)?(\d{4}/S\s*\d+-\d+|\d+-\d{4})\b", re.IGNORECASE)


def fix_mojibake(text: str) -> str:
    """Repair text that was decoded as cp1252 although it was UTF-8."""
    if not _MOJIBAKE_RE.search(text):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if len(_MOJIBAKE_RE.findall(repaired)) < len(_MOJIBAKE_RE.findall(text)):
        return repaired
    return text


def strip_page_noise(text: str) -> str:
    text = _PAGE_FOOTER_RE.sub("", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return _BLANK_RUN_RE.sub("\n", text).strip()


def _page_text(page: Any) -> str:
    if isinstance(page, dict):
        return str(page.get("text") or "")
    return str(getattr(page, "text", "") or "")


def _page_number(page: Any, fallback: int) -> int:
    if isinstance(page, dict):
        value = page.get("n", fallback)
    else:
        value = getattr(page, "n", fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def prepare_ocr_text(
    pages: list[Any],
    *,
    trim: bool = True,
    head_chars: int = 8000,
    tail_chars: int = 2000,
) -> str:
    """Join cached pages into one prompt-ready string.

    When `trim` is on, documents longer than head+tail keep the head (where
    the identifying metadata lives) and the tail, with an explicit marker so
    the model knows text was omitted.
    """
    chunks: list[str] = []
    for index, page in enumerate(pages, start=1):
        text = strip_page_noise(fix_mojibake(_page_text(page)))
        if text:
            chunks.append(f"[strona {_page_number(page, index)}]\n{text}")
    text = "\n\n".join(chunks)
    text = unicodedata.normalize("NFC", text)

    if trim and len(text) > head_chars + tail_chars:
        omitted = len(text) - head_chars - tail_chars
        text = (
            text[:head_chars]
            + f"\n\n[ŚCIĘTO {omitted} ZNAKÓW — dalsza treść nie zawiera nagłówka]\n\n"
            + text[-tail_chars:]
        )
    return text


def _dedupe(values: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = re.sub(r"\s+", "", value).upper()
        if key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def candidate_hints(text: str) -> str | None:
    """Regex + checksum derived candidates, for the optional E2 hint block."""
    nips = [v for v in _NIP_RE.findall(text) if nip_valid(v)]
    nrbs = [v for v in _NRB_RE.findall(text) if nrb_valid(v)]
    lines = [
        ("NIP", _dedupe(nips)),
        ("NRB", _dedupe(nrbs)),
        ("daty", _dedupe(_DATE_RE.findall(text))),
        ("kwoty", _dedupe(_MONEY_RE.findall(text))),
        ("BZP", _dedupe(_BZP_RE.findall(text))),
        ("TED", _dedupe(_TED_RE.findall(text))),
    ]
    present = [f"{label}: {', '.join(values)}" for label, values in lines if values]
    return "\n".join(present) if present else None
