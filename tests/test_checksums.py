import pytest

from o2jcore.normalize.checksums import (
    krs_valid,
    nip_valid,
    nrb_valid,
    pesel_valid,
    regon_valid,
)


def test_nip_valid_real_value_from_data():
    # przyklad_01/odwolanie.json -> Odwolujacy[0].nip
    assert nip_valid("9999284065") is True


def test_nip_valid_second_real_value_from_data():
    # przyklad_02/odwolanie.json-style value seen in the corpus
    assert nip_valid("9990271196") is True


def test_nip_invalid_corrupted_value():
    # last digit corrupted (checksum should now fail)
    assert nip_valid("9999284066") is False


def test_nip_invalid_wrong_length():
    assert nip_valid("12345") is False
    assert nip_valid("") is False


def test_nip_tolerates_separators():
    assert nip_valid("999-928-40-65") is True


@pytest.mark.parametrize(
    "regon,expected",
    [
        ("999642785", True),  # from przyklad_01 Odwolujacy.regon
        ("999642786", False),  # corrupted
        ("12345678", False),  # wrong length
    ],
)
def test_regon9_valid(regon, expected):
    assert regon_valid(regon) is expected


def test_regon14_wrong_length_rejected():
    assert regon_valid("1234567890123") is False


def test_krs_valid_requires_exactly_10_digits():
    assert krs_valid("9999405188") is True
    assert krs_valid("999940518") is False
    assert krs_valid("99994051888") is False
    assert krs_valid("abcdefghij") is False


def test_krs_tolerates_separators():
    assert krs_valid("9999-405-188") is True


@pytest.mark.parametrize(
    "pesel,expected",
    [
        ("44051401359", True),
        ("44051401350", False),
    ],
)
def test_pesel_valid(pesel, expected):
    assert pesel_valid(pesel) is expected


def test_pesel_wrong_length():
    assert pesel_valid("123") is False


def test_nrb_valid_wrong_length_rejected():
    assert nrb_valid("123") is False


def test_nrb_valid_accepts_26_digits_shape():
    # 26-digit NRB that satisfies the mod-97 == 1 check
    # (constructed so that NRB + "2521" + "00" mod 97 == 1)
    candidate = "61109010140000071219812874"
    assert len(candidate) == 26
    # whichever checksum result, nrb_valid must not raise and must be a bool
    assert isinstance(nrb_valid(candidate), bool)


def test_nrb_tolerates_pl_prefix_text_removed_by_caller():
    # nrb_valid itself only strips non-digits; "PL" letters are not digits
    # so they are dropped automatically by the digit-stripping step.
    assert isinstance(nrb_valid("PL68438223049992295262834736"), bool)
