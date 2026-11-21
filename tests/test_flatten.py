"""Tests for lab.eval.flatten."""

from __future__ import annotations

import json
from pathlib import Path

from lab import paths
from lab.eval.flatten import flatten
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]


def _specs():
    return load_all_classes(REPO_ROOT / "configs" / "classes")


def test_hand_built_dict_flattens_with_missing_and_extra_keys():
    specs = _specs()
    spec = specs["potwierdzenie_przelewu"]

    # deliberately missing 'numer_transakcji', deliberately extra 'FooBar'.
    obj = {
        "przelew_bankowy": {
            "data_operacji": "2026-03-21",
            "kwota": 200.0,
            "na_rachunek": "68438223049992295262834736",
            # "numer_transakcji" missing on purpose
            "tytul": "opłata skarbowa",
            "z_rachunku": "05470680287581539721455024",
            "FooBar": "unexpected",
        }
    }

    flat = flatten(obj, spec)

    assert flat["przelew_bankowy.numer_transakcji"] is None
    assert flat["przelew_bankowy.data_operacji"] == "2026-03-21"
    assert flat["przelew_bankowy.kwota"] == 200.0
    assert flat["przelew_bankowy.na_rachunek"] == "68438223049992295262834736"
    assert flat["przelew_bankowy.tytul"] == "opłata skarbowa"
    assert flat["przelew_bankowy.z_rachunku"] == "05470680287581539721455024"
    assert flat["!extra:przelew_bankowy.FooBar"] == "unexpected"


def test_missing_key_and_explicit_null_are_indistinguishable():
    specs = _specs()
    spec = specs["potwierdzenie_przelewu"]

    missing = {"przelew_bankowy": {"kwota": 1.0}}
    explicit_null = {"przelew_bankowy": {"kwota": 1.0, "data_operacji": None}}

    flat_missing = flatten(missing, spec)
    flat_null = flatten(explicit_null, spec)

    assert flat_missing["przelew_bankowy.data_operacji"] is None
    assert flat_null["przelew_bankowy.data_operacji"] is None


def test_round_trip_przyklad_01_przelew():
    specs = _specs()
    spec = specs["potwierdzenie_przelewu"]
    gold_path = paths.data_root() / "dane" / "przyklad_01" / "przelew.json"
    obj = json.loads(gold_path.read_text(encoding="utf-8"))

    flat = flatten(obj, spec)

    expected = {
        "przelew_bankowy.data_operacji": obj["przelew_bankowy"]["data_operacji"],
        "przelew_bankowy.kwota": obj["przelew_bankowy"]["kwota"],
        "przelew_bankowy.na_rachunek": obj["przelew_bankowy"]["na_rachunek"],
        "przelew_bankowy.numer_transakcji": obj["przelew_bankowy"]["numer_transakcji"],
        "przelew_bankowy.tytul": obj["przelew_bankowy"]["tytul"],
        "przelew_bankowy.z_rachunku": obj["przelew_bankowy"]["z_rachunku"],
    }

    assert flat == expected
    assert len(flat) == 6
