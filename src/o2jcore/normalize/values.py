"""Registry of value normalizers used to reconcile model output with gold data.

Every normalizer in NORMALIZERS must be idempotent: f(f(x)) == f(x).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from .dates_pl import parse_date_pl

_DIGITS_RE = re.compile(r"\D")
_WHITESPACE_RE = re.compile(r"\s+")

_TED_PLAIN_RE = re.compile(r"^(\d+)-(\d{4})$")
_TED_TED_FORM_RE = re.compile(r"^(\d{4})/S\s*\d+-(\d+)$", re.IGNORECASE)

_MONEY_CURRENCY_RE = re.compile(r"(z[łl]|PLN)", re.IGNORECASE)


def date_iso(v: Any) -> str | None:
    if v is None:
        return None
    return parse_date_pl(str(v))


def digits(v: Any) -> str | None:
    if v is None:
        return None
    result = _DIGITS_RE.sub("", str(v))
    return result or None


def nrb26(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s[:2].upper() == "PL":
        s = s[2:]
    result = _DIGITS_RE.sub("", s)
    return result or None


def bzp(v: Any) -> str | None:
    if v is None:
        return None
    s = _WHITESPACE_RE.sub("", str(v)).upper()
    return s or None


def ted(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    m = _TED_PLAIN_RE.match(s)
    if m:
        return s
    m = _TED_TED_FORM_RE.match(s)
    if m:
        year, num = m.group(1), m.group(2)
        return f"{num}-{year}"
    return None


def money(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = _MONEY_CURRENCY_RE.sub("", s).strip()
    # treat any whitespace (incl. non-breaking / narrow no-break spaces) as a
    # thousands-group separator to be dropped
    s = re.sub(r"\s", "", s)
    if "," in s:
        # comma is the decimal separator; dots are thousands separators
        s = s.replace(".", "")
        s = s.replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    s = unicodedata.normalize("NFC", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s or None


_TITLE_RE = re.compile(
    r"^(?:(?:r\.\s*pr\.|radca\s+prawny|adw\.|mec\.|mgr|dr)\.?\s*)+",
    re.IGNORECASE,
)


def name(v: Any) -> str | None:
    s = text(v)
    if s is None:
        return None
    return _TITLE_RE.sub("", s).strip() or None


def enum_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def identity(v: Any) -> Any:
    return v


NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "date_iso": date_iso,
    "digits": digits,
    "nrb26": nrb26,
    "bzp": bzp,
    "ted": ted,
    "money": money,
    "text": text,
    "name": name,
    "enum_int": enum_int,
    "identity": identity,
}


def get(name: str) -> Callable[[Any], Any]:
    return NORMALIZERS[name]


def normalize(name: str, value: Any) -> Any:
    if value is None:
        return None
    return NORMALIZERS[name](value)
