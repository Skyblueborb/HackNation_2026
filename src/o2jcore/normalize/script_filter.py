"""Removal of CJK/Japanese/Korean codepoints leaked by the extraction model.

A small quantized LLM can emit a single high-frequency CJK token inside an
otherwise correct string, even at temperature=0. The JSON-Schema grammar
constrains structure, not script, so this post-filter is the only backstop.

None of our three Polish document classes can contain any of these ranges:
the highest non-ASCII codepoint in all 180 gold values is U+2013 (EN DASH).
Polish letters live in Latin-1 Supplement / Latin Extended-A (U+00C0-U+017F),
far below the lowest range stripped here.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "ᄀ-ᇿ"  # Hangul Jamo
    "⺀-⻿"  # CJK Radicals Supplement
    "⼀-⿟"  # Kangxi Radicals
    "⿰-⿿"  # Ideographic Description Characters
    "　-〿"  # CJK Symbols and Punctuation
    "぀-ゟ"  # Hiragana
    "゠-ヿ"  # Katakana
    "㄀-ㄯ"  # Bopomofo
    "㄰-㆏"  # Hangul Compatibility Jamo
    "㆐-㆟"  # Kanbun
    "ㆠ-ㆿ"  # Bopomofo Extended
    "㇀-㇯"  # CJK Strokes
    "ㇰ-ㇿ"  # Katakana Phonetic Extensions
    "㈀-㋿"  # Enclosed CJK Letters and Months
    "㌀-㏿"  # CJK Compatibility
    "㐀-䶿"  # CJK Unified Ideographs Extension A
    "一-鿿"  # CJK Unified Ideographs  <-- the common leak
    "ꥠ-꥿"  # Hangul Jamo Extended-A
    "가-힣"  # Hangul Syllables        <-- the common leak
    "ힰ-퟿"  # Hangul Jamo Extended-B
    "豈-﫿"  # CJK Compatibility Ideographs
    "︐-︟"  # Vertical Forms
    "︰-﹏"  # CJK Compatibility Forms
    "＀-￯"  # Halfwidth and Fullwidth Forms
    "\U0001f200-\U0001f2ff"  # Enclosed Ideographic Supplement
    "\U00020000-\U0002a6df"  # CJK Unified Ideographs Extension B
    "\U0002a700-\U0002ebef"  # CJK Unified Ideographs Extensions C-F
    "\U0002f800-\U0002fa1f"  # CJK Compatibility Ideographs Supplement
    "\U00030000-\U000323af"  # CJK Unified Ideographs Extensions G-H
    "]"
)
_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")


def strip_foreign_scripts(value: str) -> tuple[str, int]:
    """Return (cleaned, n_removed). Idempotent: f(f(x))[0] == f(x)[0]."""
    matches = _FOREIGN_SCRIPT_RE.findall(value)
    if not matches:
        return value, 0
    cleaned = _FOREIGN_SCRIPT_RE.sub("", value)
    # the strip can weld two words together with a double space; collapse it
    cleaned = _SPACE_RUN_RE.sub(" ", cleaned).strip()
    logger.warning(
        "stripped %d foreign-script codepoint(s) from model output: %s",
        len(matches),
        " ".join(f"U+{ord(c):04X}" for c in dict.fromkeys(matches)),
    )
    return cleaned, len(matches)


def sanitize_payload(value: Any) -> tuple[Any, int]:
    """Recursively strip foreign-script codepoints from a parsed LLM payload.

    Walks dicts (keys *and* values), lists and strings; every other type passes
    through untouched. Returns (sanitized, total_removed). When sanitizing a key
    collides with an existing key, the pre-existing entry wins.
    """
    if isinstance(value, str):
        return strip_foreign_scripts(value)
    if isinstance(value, dict):
        total = 0
        out: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = key
            if isinstance(key, str):
                new_key, removed = strip_foreign_scripts(key)
                total += removed
            new_item, removed = sanitize_payload(item)
            total += removed
            out.setdefault(new_key, new_item)
        return out, total
    if isinstance(value, list):
        total = 0
        out_list: list[Any] = []
        for item in value:
            new_item, removed = sanitize_payload(item)
            total += removed
            out_list.append(new_item)
        return out_list, total
    return value, 0
