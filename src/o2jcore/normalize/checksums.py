"""Checksum validators for Polish identifiers (NIP, REGON, KRS, NRB, PESEL).

Every validator tolerates separators (spaces, dashes, dots) by stripping all
non-digit characters before checking.
"""

from __future__ import annotations

import re

_NON_DIGIT_RE = re.compile(r"\D")


def _digits_only(s: str) -> str:
    return _NON_DIGIT_RE.sub("", s or "")


def nip_valid(s: str) -> bool:
    digits = _digits_only(s)
    if len(digits) != 10:
        return False
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    checksum = total % 11
    if checksum == 10:
        return False
    return checksum == int(digits[9])


def regon_valid(s: str) -> bool:
    digits = _digits_only(s)
    if len(digits) == 9:
        weights = [8, 9, 2, 3, 4, 5, 6, 7]
        total = sum(int(d) * w for d, w in zip(digits[:8], weights))
        checksum = total % 11
        if checksum == 10:
            checksum = 0
        return checksum == int(digits[8])
    if len(digits) == 14:
        weights = [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]
        total = sum(int(d) * w for d, w in zip(digits[:13], weights))
        checksum = total % 11
        if checksum == 10:
            checksum = 0
        return checksum == int(digits[13])
    return False


def krs_valid(s: str) -> bool:
    digits = _digits_only(s)
    return len(digits) == 10


def nrb_valid(s: str) -> bool:
    digits = _digits_only(s)
    if len(digits) != 26:
        return False
    # Polish NRB mod-97 check: append numeric country code "PL" (P=25, L=21)
    # and a "00" placeholder for the IBAN check digits, then verify mod 97 == 1.
    candidate = digits + "2521" + "00"
    return int(candidate) % 97 == 1


def pesel_valid(s: str) -> bool:
    digits = _digits_only(s)
    if len(digits) != 11:
        return False
    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    total = sum(int(d) * w for d, w in zip(digits[:10], weights))
    checksum = (10 - (total % 10)) % 10
    return checksum == int(digits[10])
