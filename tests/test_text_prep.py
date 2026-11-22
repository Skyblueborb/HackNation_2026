"""Tests for deterministic OCR text preparation."""

from __future__ import annotations

import json
from pathlib import Path

from lab import paths
from lab.llm.text_prep import (
    candidate_hints,
    fix_mojibake,
    prepare_ocr_text,
    squeeze_column_gaps,
    strip_page_noise,
)


def test_fix_mojibake_repairs_cp1252_decoded_polish():
    assert fix_mojibake("RozwiÄ…zania S.A.") == "Rozwiązania S.A."


def test_fix_mojibake_leaves_correct_utf8_alone():
    assert fix_mojibake("Rozwiązania S.A.") == "Rozwiązania S.A."


def test_strip_page_noise_removes_repeated_footers():
    raw = "Nagłówek\nStrona 1 z 2\nTreść\nPage 2 of 3\nKoniec"
    assert strip_page_noise(raw) == "Nagłówek\nTreść\nKoniec"


def test_prepare_ocr_text_marks_pages_and_truncates_long_documents():
    pages = [{"n": 1, "text": "A" * 1500}, {"n": 2, "text": "B" * 1500}]
    text = prepare_ocr_text(pages, head_chars=1000, tail_chars=1600)
    assert "[strona 1]" in text
    assert "[strona 2]" in text
    assert "[ŚCIĘTO" in text
    assert len(text) < 3000


def test_prepare_ocr_text_without_trim_keeps_everything():
    pages = [{"n": 1, "text": "A" * 5000}, {"n": 2, "text": "B" * 5000}]
    text = prepare_ocr_text(pages, trim=False)
    assert len(text) == 10000 + len("\n\n".join(["[strona 1]\n", "[strona 2]\n"]))
    assert "ŚCIĘTO" not in text


def test_candidate_hints_finds_real_bzp_numbers():
    text = "Postępowanie nr 2026/BZP00999518 oraz 2026/BZP 00999033/03."

    hints = candidate_hints(text)

    assert hints is not None
    assert "BZP: 2026/BZP00999518, 2026/BZP 00999033/03" in hints


def test_candidate_hints_uses_checksum_valid_nip_from_real_gold():
    gold = json.loads(
        (paths.data_root() / "dane" / "przyklad_01" / "odwolanie.json").read_text(encoding="utf-8")
    )
    nip = gold["Odwolujacy"][0]["nip"]
    assert nip
    hints = candidate_hints(f"NIP: {nip}\n")
    assert hints is not None
    assert f"NIP: {nip}" in hints


def test_squeeze_column_gaps_marks_the_break_and_drops_the_padding():
    raw = "   Bartosz Zajkowski                  Oliwia Gajewski              \n\n   Prokurent\n"
    assert squeeze_column_gaps(raw) == "   Bartosz Zajkowski   Oliwia Gajewski\n   Prokurent"


def test_squeeze_column_gaps_keeps_single_spaces_inside_a_phrase():
    assert squeeze_column_gaps("Za Silvatica Technologie sp. z o.o.") == (
        "Za Silvatica Technologie sp. z o.o."
    )
