"""Parse Polish-language dates into ISO 8601 (YYYY-MM-DD)."""

from __future__ import annotations

import re

_MONTHS = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "września": 9,
    "października": 10,
    "listopada": 11,
    "grudnia": 12,
}

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DOTTED_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTH_NAMES_PATTERN = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))
_PL_LONG_RE = re.compile(
    rf"^(?:dnia\s+)?(\d{{1,2}})\s+({_MONTH_NAMES_PATTERN})\s+(\d{{4}})\s*(?:roku|r\.)?$",
    re.IGNORECASE,
)


def _valid_ymd(year: int, month: int, day: int) -> bool:
    if not (1 <= month <= 12):
        return False
    try:
        import datetime

        datetime.date(year, month, day)
    except ValueError:
        return False
    return True


def parse_date_pl(s: str) -> str | None:
    """Parse a Polish-formatted date string into ISO YYYY-MM-DD, or None."""
    if s is None:
        return None
    text = s.strip()
    if not text:
        return None

    m = _ISO_RE.match(text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    m = _DOTTED_RE.match(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    m = _SLASH_RE.match(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    m = _PL_LONG_RE.match(text)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        month = _MONTHS.get(month_name)
        if month is not None and _valid_ymd(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    return None
