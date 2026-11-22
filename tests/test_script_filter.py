"""Unit tests for the foreign-script (CJK/Hangul) sanitation pass."""

from __future__ import annotations

from o2jcore.normalize.script_filter import sanitize_payload, strip_foreign_scripts

DIRTY_SAMPLES = [
    "Odwo的łanie",
    "Zamawiający가",
    "Sąd Okręgowy 的 w Warszawie",
    "NIP：１23",
    "的的",
    "Ext\U00020000B",
]


def test_clean_string_returned_unchanged_with_zero_count():
    clean = "Odwołanie do KIO"
    result, removed = strip_foreign_scripts(clean)
    assert (result, removed) == (clean, 0)
    assert result is clean


def test_strips_single_cjk_ideograph():
    assert strip_foreign_scripts("Odwo的łanie") == ("Odwołanie", 1)


def test_strips_hangul_syllable():
    assert strip_foreign_scripts("Zamawiający가") == ("Zamawiający", 1)


def test_polish_diacritics_pass_through_untouched():
    polish = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ–"
    result, removed = strip_foreign_scripts(polish)
    assert removed == 0
    assert result == polish
    for char in polish:
        assert strip_foreign_scripts(char) == (char, 0)


def test_mixed_script_string_collapses_welded_space():
    assert strip_foreign_scripts("Sąd Okręgowy 的 w Warszawie") == (
        "Sąd Okręgowy w Warszawie",
        1,
    )


def test_fullwidth_forms_stripped():
    assert strip_foreign_scripts("NIP：１23") == ("NIP23", 2)


def test_astral_plane_ideograph_stripped():
    assert strip_foreign_scripts("Ext\U00020000B") == ("ExtB", 1)


def test_idempotent():
    for sample in DIRTY_SAMPLES:
        once, _ = strip_foreign_scripts(sample)
        assert strip_foreign_scripts(once) == (once, 0)


def test_string_entirely_foreign_becomes_empty():
    assert strip_foreign_scripts("的的") == ("", 2)


def test_sanitize_payload_walks_nested_dicts_and_lists():
    payload = {"a": {"b": [{"c": "x的"}]}}
    assert sanitize_payload(payload) == ({"a": {"b": [{"c": "x"}]}}, 1)


def test_sanitize_payload_sanitizes_keys():
    assert sanitize_payload({"naz的wa": "X"}) == ({"nazwa": "X"}, 1)


def test_sanitize_payload_key_collision_keeps_existing():
    assert sanitize_payload({"nazwa": "A", "naz的wa": "B"}) == ({"nazwa": "A"}, 1)


def test_sanitize_payload_leaves_non_strings_alone():
    payload = {"k": 1, "f": 1.5, "b": True, "n": None}
    result, removed = sanitize_payload(payload)
    assert removed == 0
    assert result == payload


def test_sanitize_payload_is_idempotent():
    payload = {"naz的wa": ["A的", {"b": "的"}], "n": None}
    once, first = sanitize_payload(payload)
    twice, second = sanitize_payload(once)
    assert first == 3
    assert second == 0
    assert twice == once
