import pytest

from o2jcore.normalize.dates_pl import parse_date_pl

CASES = [
    ("2026-11-09", "2026-11-09"),
    ("09.11.2026", "2026-11-09"),
    ("9.11.2026", "2026-11-09"),
    ("09/11/2026", "2026-11-09"),
    ("9 listopada 2026 roku", "2026-11-09"),
    ("dnia 9 listopada 2026 r.", "2026-11-09"),
    ("1 stycznia 2026", "2026-01-01"),
    ("1 lutego 2026", "2026-02-01"),
    ("1 marca 2026", "2026-03-01"),
    ("1 kwietnia 2026", "2026-04-01"),
    ("1 maja 2026", "2026-05-01"),
    ("1 czerwca 2026", "2026-06-01"),
    ("1 lipca 2026", "2026-07-01"),
    ("1 sierpnia 2026", "2026-08-01"),
    ("1 września 2026", "2026-09-01"),
    ("1 WRZEŚNIA 2026", "2026-09-01"),
    ("1 października 2026", "2026-10-01"),
    ("1 listopada 2026", "2026-11-01"),
    ("1 grudnia 2026", "2026-12-01"),
    (" ", None),
    ("", None),
    ("not a date", None),
    ("32.13.2026", None),
    ("2026-13-01", None),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_parse_date_pl(raw, expected):
    assert parse_date_pl(raw) == expected


def test_parse_date_pl_none_input():
    assert parse_date_pl(None) is None


@pytest.mark.parametrize("raw,expected", [c for c in CASES if c[1] is not None])
def test_parse_date_pl_idempotent(raw, expected):
    assert parse_date_pl(parse_date_pl(raw)) == expected
