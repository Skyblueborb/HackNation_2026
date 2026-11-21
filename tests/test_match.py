"""Tests for lab.eval.match (element_similarity, greedy_align)."""

from __future__ import annotations

import math
from pathlib import Path

from lab.eval.flatten import relative_fields
from lab.eval.match import element_similarity, greedy_align
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]


def _specs():
    return load_all_classes(REPO_ROOT / "configs" / "classes")


def _pelnomocnicy_list_spec_and_fields():
    spec = _specs()["pelnomocnictwo"]
    list_spec = next(f for f in spec.fields if f.path == "pelnomocnicy[]").list_spec
    field_specs = relative_fields(spec.fields, "pelnomocnicy[]")
    return list_spec, field_specs


def test_element_similarity_identical_dicts_is_one():
    list_spec, field_specs = _pelnomocnicy_list_spec_and_fields()
    elem = {"imie_nazwisko": "Jan Kowalski", "pesel": "12345678901"}

    score = element_similarity(elem, elem, list_spec, field_specs)

    assert score == 1.0


def test_element_similarity_nothing_in_common_is_zero_not_nan():
    list_spec, field_specs = _pelnomocnicy_list_spec_and_fields()
    pred_elem = {"imie_nazwisko": None, "pesel": None}
    gold_elem = {"imie_nazwisko": None, "pesel": None}

    # both-null on every field -> zero comparable leaves after exclusion -> 0.0
    score = element_similarity(pred_elem, gold_elem, list_spec, field_specs)

    assert score == 0.0
    assert not math.isnan(score)


def test_greedy_align_permuted_two_element_list():
    list_spec, field_specs = _pelnomocnicy_list_spec_and_fields()
    gold_list = [
        {"imie_nazwisko": "Aleksandra Marciniak", "pesel": None},
        {"imie_nazwisko": "Jolanta Zajkowski", "pesel": None},
    ]
    pred_list = list(reversed(gold_list))  # swapped order

    pairs = greedy_align(pred_list, gold_list, list_spec, field_specs)

    assert set(pairs) == {(1, 0), (0, 1)}


def test_greedy_align_spurious_extra_pred_element():
    list_spec, field_specs = _pelnomocnicy_list_spec_and_fields()
    gold_list = [
        {"imie_nazwisko": "Aleksandra Marciniak", "pesel": None},
        {"imie_nazwisko": "Jolanta Zajkowski", "pesel": None},
    ]
    pred_list = gold_list + [{"imie_nazwisko": "Zupelnie Inna Osoba", "pesel": "99999999999"}]

    pairs = greedy_align(pred_list, gold_list, list_spec, field_specs)

    assert (2, None) in pairs
    assert (0, 0) in pairs
    assert (1, 1) in pairs
    assert len(pairs) == 3


def test_greedy_align_missed_gold_element():
    list_spec, field_specs = _pelnomocnicy_list_spec_and_fields()
    gold_list = [
        {"imie_nazwisko": "Aleksandra Marciniak", "pesel": None},
        {"imie_nazwisko": "Jolanta Zajkowski", "pesel": None},
    ]
    pred_list = [gold_list[0]]  # model never produced the second entity

    pairs = greedy_align(pred_list, gold_list, list_spec, field_specs)

    assert (0, 0) in pairs
    assert (None, 1) in pairs
    assert len(pairs) == 2
