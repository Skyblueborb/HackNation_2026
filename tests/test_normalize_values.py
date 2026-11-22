import pytest

from o2jcore.normalize import values as v


def test_digits_preserves_leading_zeros():
    assert v.digits("000279077") == "000279077"


def test_digits_strips_separators():
    assert v.digits("999-999-99-99") == "9999999999"


def test_digits_none_on_empty():
    assert v.digits("abc") is None
    assert v.digits(None) is None


def test_bzp_normalizes_spacing():
    assert v.bzp("2026/BZP 00999518") == "2026/BZP00999518"


def test_bzp_preserves_correction_suffix():
    assert v.bzp("2026/BZP 00999033/03") == "2026/BZP00999033/03"


def test_bzp_uppercases_token():
    assert v.bzp("2026/bzp 00999518") == "2026/BZP00999518"


def test_ted_accepts_already_correct():
    assert v.ted("641651-2026") == "641651-2026"


def test_ted_reorders_ted_form():
    assert v.ted("2026/S 199-999065") == "999065-2026"


def test_ted_invalid_returns_none():
    assert v.ted("not-a-ted") is None
    assert v.ted("") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("15 000,00 zł", 15000.0),
        ("15.000,00", 15000.0),
        ("200,00 PLN", 200.0),
        ("200.0", 200.0),
        (200.0, 200.0),
        (200, 200.0),
        ("17", 17.0),
        ("50,00", 50.0),
    ],
)
def test_money(raw, expected):
    assert v.money(raw) == expected


def test_money_unparseable_returns_none():
    assert v.money("not money") is None
    assert v.money(None) is None


def test_text_keeps_case_and_diacritics():
    assert v.text("  Filharmonia   Pomorska \n") == "Filharmonia Pomorska"


def test_text_empty_returns_none():
    assert v.text("   ") is None
    assert v.text(None) is None


def test_name_is_text():
    assert v.name("  Jan   Kowalski ") == "Jan Kowalski"


def test_name_strips_leading_professional_titles():
    assert v.name("adw. Piotr Zalewski") == "Piotr Zalewski"
    assert v.name("r. pr. Jan Kowalski") == "Jan Kowalski"
    assert v.name("radca prawny Anna Nowak") == "Anna Nowak"


def test_enum_int():
    assert v.enum_int(9) == 9
    assert v.enum_int("9") == 9
    assert v.enum_int(None) is None
    assert v.enum_int("abc") is None


def test_identity():
    assert v.identity("x") == "x"
    assert v.identity(None) is None


def test_nrb26_keeps_country_prefix_and_strips_whitespace():
    assert v.nrb26("PL 68 4382 2304 9992 2952 6283 4736") == "PL68438223049992295262834736"
    assert v.nrb26("68438223049992295262834736") == "68438223049992295262834736"
    assert v.nrb26("pl68438223049992295262834736") == "PL68438223049992295262834736"


def test_nrb26_does_not_pad_or_truncate():
    assert v.nrb26("123") == "123"


def test_normalize_passes_through_none():
    assert v.normalize("digits", None) is None
    assert v.normalize("money", None) is None


@pytest.mark.parametrize(
    "fn_name,raw",
    [
        ("date_iso", "9 listopada 2026 roku"),
        ("digits", "000279077"),
        ("nrb26", "PL68438223049992295262834736"),
        ("bzp", "2026/BZP 00999518"),
        ("ted", "2026/S 199-999065"),
        ("money", "15 000,00 zł"),
        ("text", "  Filharmonia   Pomorska \n"),
        ("name", "  Jan   Kowalski "),
        ("enum_int", "9"),
        ("identity", "x"),
    ],
)
def test_idempotent(fn_name, raw):
    fn = v.get(fn_name)
    once = fn(raw)
    twice = fn(once)
    assert once == twice
