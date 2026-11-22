"""Tests for post-extraction grounding, derived fields and class routing."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from lab import paths
from lab.cache import read_cached
from lab.llm.classify import classify_by_rules
from lab.llm import grounding
from lab.llm.grounding import enforce_derived, ground_object
from lab.llm.text_prep import prepare_ocr_text
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = paths.data_root() / "dane"
SPECS = load_all_classes(REPO_ROOT / "configs" / "classes")


def _text(set_id: str, cid: str) -> str:
    pdf = GOLD_DIR / set_id / f"{SPECS[cid].pdf_stem}.pdf"
    cached = read_cached(paths.work_root() / "cache", pdf, "pdfplumber")
    assert cached is not None
    return prepare_ocr_text(cached["pages"])


def test_grounding_nulls_ungrounded_free_text_but_not_dates():
    spec = SPECS["odwolanie"]
    obj = json.loads((GOLD_DIR / "przyklad_01" / "odwolanie.json").read_text(encoding="utf-8"))
    obj = copy.deepcopy(obj)
    original_date = obj["OdwolanieKIO"]["data"]
    obj["OdwolanieKIO"]["miejscowosc"] = "Zmyślone Miasto Kujawskie"

    nulled = ground_object(obj, spec, _text("przyklad_01", "odwolanie"))

    assert nulled >= 1
    assert obj["OdwolanieKIO"]["miejscowosc"] is None
    assert obj["OdwolanieKIO"]["data"] == original_date


def test_enforce_derived_repairs_czynnosc_opis_from_enum_map():
    spec = SPECS["odwolanie"]
    obj = json.loads((GOLD_DIR / "przyklad_01" / "odwolanie.json").read_text(encoding="utf-8"))
    enum = yaml.safe_load((REPO_ROOT / "configs/enums/czynnosc_powod.yaml").read_text(encoding="utf-8"))
    key = int(obj["OdwolanieKIO"]["czynnosc_powod_id"])
    obj["OdwolanieKIO"]["czynnosc_opis"] = "zły opis"

    changed = enforce_derived(obj, spec)

    assert changed == 1
    assert obj["OdwolanieKIO"]["czynnosc_opis"] == enum[key]


def test_classify_rules_routes_all_180_pdfs_from_text_alone():
    """Routing must hold without the filename, which the graded set randomises."""
    for set_dir in sorted(GOLD_DIR.glob("przyklad_*")):
        for cid in SPECS:
            assert classify_by_rules(_text(set_dir.name, cid)) == cid


def test_classify_rules_returns_none_for_empty_text():
    assert classify_by_rules("") is None


# --- czynnosc_powod_id ------------------------------------------------------
# Every sentence below is verbatim OCR text from the 10 odwolanie documents in
# the dev split, paired with its gold id. przyklad_04 carries the OCR doubling
# ("unieważniił"); przyklad_50 and _59 need the window past the first clause.
CZYNNOSC_CASES = [
    (1, "Zamawiający w dniu 11 sierpnia 2026 roku poinformował o odrzuceniu oferty złożonej przez\nOdwołującego.\nZarzut nr 1 naruszenia obowiązku sporządzenia dokumentacji"),
    (4, "Zamawiający w dniu 3 czerwca 2026 roku opublikował Specyfikację Warunków Zamówienia.\nZarzut nr 1 naruszenia zasady racjonalnego gospodarowania środkami publicznymi:\n1).1. Zamawiający nie przedstawił rachunku ekonomicznego dla rozwiązań opisanych w Opisie\nPrzedmiotu Zamówienia"),
    (6, "Zamawiający w dniu 3 czerwca 2026 roku przekazał wykonawcom odpowiedzi i\nwyjaśnienia do treści Specyfikacji Warunków Zamówienia.\nZarzut nr 1 naruszenia zasady równego traktowania wykonawców:\n1).1. Opis Przedmiotu Zamówienia wskazuje rozwiązania"),
    (8, "Zamawiający w dniu 27 października 2026 roku nie wykluczył z postępowania podmiotu działającego\nw grupie kapitałowej.\nZarzut nr 1"),
    (8, "Zamawiający w dniu 2 czerwca 2026 roku przekazał informację o wyniku postępowania, z której\nwynika, że zaniechał wykluczenia wykonawcy Trivex Farmacja sp. z o.o., mimo istnienia\npodstaw wykluczenia. Uprzednio, w dniu 11 kwietnia 2026 r., Zamawiający wezwał\nwykonawców do złożenia wyjaśnień i dokumentów.\nZaskarżonym czynnościom i zaniechaniom Zamawiającego zarzucam naruszenie:"),
    (9, "Zamawiający w dniu 11 sierpnia 2026 roku unieważniił postępowanie.\nZarzut nr 1 nieopisania parametrów technicznych przedmiotu dostawy:"),
    (10, "Zamawiający w dniu 20 lutego 2026 roku zaniechał unieważnienia postępowania.\nZarzut nr 3 zaniechania wezwania do wyjaśnień"),
    (11, "Zamawiający w dniu 21 września 2026 roku opublikował dokumenty zamówienia, w tym\nOpis Przedmiotu Zamówienia stanowiący Załącznik nr 1 do SWZ. Wcześniej, w dniu 26\nwrześnia 2026 r., Zamawiający udzielił odpowiedzi na pierwszy zestaw pytań\nwykonawców.\nZaskarżonym czynnościom i zaniechaniom Zamawiającego zarzucam naruszenie:"),
]


@pytest.mark.parametrize("expected,text", CZYNNOSC_CASES)
def test_czynnosc_window_maps_to_gold_id(expected, text):
    window = grounding._czynnosc_window(text)
    assert window is not None
    matched = next(
        (value for value, pattern in grounding._CZYNNOSC_RULES if re.search(pattern, window)),
        None,
    )
    assert matched == expected


def test_czynnosc_omission_beats_the_verb_it_contains():
    """"zaniechał unieważnienia" must not fall through to 9 ("unieważnił")."""
    window = grounding._czynnosc_window(
        "Zamawiający w dniu 20 lutego 2026 roku zaniechał unieważnienia postępowania."
    )
    first = next(
        value for value, pattern in grounding._CZYNNOSC_RULES if re.search(pattern, window)
    )
    assert first == 10


def test_czynnosc_window_absent_leaves_no_window():
    assert grounding._czynnosc_window("Odwołanie bez zdania o czynności.") is None


# --- deterministic post-fill -----------------------------------------------
# Header and identifier blocks as pdfplumber_layout renders them: a leading
# indent, three spaces for a column break. Text is from przyklad_42, whose
# "Zamawiający (…)" label wraps its colon onto the next line and whose block
# goes on to list a consortium partner with identifiers of its own.
_HEADER_BLOCK = """[strona 1]
Prezes Krajowej Izby Odwoławczej
   ul. Postępu 17A
   02-676 Warszawa
   Odwołujący:
   Valtrix Systemy Informatyczne sp. z o.o.
   ul. Grunwaldzka 112, 60-307 Poznań
   KRS: 9998213547, NIP: 9993380162, REGON: 999517204
   Zamawiający (zamawiający wspólnie przeprowadzający postępowanie na podstawie art. 38 ust.
   1 Pzp):
   1) Zamawiający – Lider, prowadzący postępowanie:
   Regionalne Centrum Usług Medycznych sp. z o.o.
   KRS: 9991840562, NIP: 9998802341, REGON: 999015873
   2) Zamawiający – Partner:
   Medisoft Integracje S.A.
   KRS: 9997092068, NIP: 9992642441, REGON: 999764975
   Poznań, dnia 19 października 2026 r.
"""


def _empty_odwolanie() -> dict:
    return {
        "OdwolanieKIO": {"data": None, "miejscowosc": None},
        "Odwolujacy": [{"krs": None, "nip": None, "regon": None}],
        "Zamawiajacy": [{"krs": None, "nip": None, "regon": None}],
    }


def test_enforce_header_reads_city_and_date_past_the_parties_block():
    obj = _empty_odwolanie()
    assert grounding.enforce_header(obj, SPECS["odwolanie"], _HEADER_BLOCK) == 2
    assert obj["OdwolanieKIO"] == {"data": "2026-10-19", "miejscowosc": "Poznań"}


def test_enforce_header_overrides_the_models_answer_where_it_matches():
    """The model's other failure here is returning the whole line as the city."""
    obj = _empty_odwolanie()
    obj["OdwolanieKIO"]["miejscowosc"] = "Poznań, dnia 19 października 2026 r."
    grounding.enforce_header(obj, SPECS["odwolanie"], _HEADER_BLOCK)
    assert obj["OdwolanieKIO"]["miejscowosc"] == "Poznań"


def test_enforce_header_leaves_the_model_alone_with_no_header_line():
    obj = _empty_odwolanie()
    obj["OdwolanieKIO"]["miejscowosc"] = "Gdańsk"
    assert grounding.enforce_header(obj, SPECS["odwolanie"], "Odwołujący:\n   ul. Huta 90\n") == 0
    assert obj["OdwolanieKIO"]["miejscowosc"] == "Gdańsk"


def test_enforce_header_ignores_an_address_line():
    obj = _empty_odwolanie()
    text = "Odwołujący:\n   ul. Topolowa 79, 85-512 Bydgoszcz\n   02-676 Warszawa\n"
    assert grounding.enforce_header(obj, SPECS["odwolanie"], text) == 0
    assert obj["OdwolanieKIO"]["miejscowosc"] is None


def test_enforce_party_ids_takes_each_party_first_line_not_the_partner():
    obj = _empty_odwolanie()
    assert grounding.enforce_party_ids(obj, SPECS["odwolanie"], _HEADER_BLOCK) == 6
    assert obj["Odwolujacy"][0] == {
        "krs": "9998213547",
        "nip": "9993380162",
        "regon": "999517204",
    }
    # The leader's numbers, not the partner's listed below them.
    assert obj["Zamawiajacy"][0] == {
        "krs": "9991840562",
        "nip": "9998802341",
        "regon": "999015873",
    }


def test_enforce_party_ids_leaves_a_party_without_a_krs_null():
    obj = _empty_odwolanie()
    text = "Zamawiający:\n   Gmina Brzozowo Pomorskie\n   NIP: 9995062817, REGON: 999871350\n"
    grounding.enforce_party_ids(obj, SPECS["odwolanie"], text)
    assert obj["Zamawiajacy"][0]["krs"] is None
    assert obj["Zamawiajacy"][0]["nip"] == "9995062817"


def test_enforce_party_ids_never_overwrites_a_non_null_value():
    obj = _empty_odwolanie()
    obj["Odwolujacy"][0]["krs"] = "1111111111"
    grounding.enforce_party_ids(obj, SPECS["odwolanie"], _HEADER_BLOCK)
    assert obj["Odwolujacy"][0]["krs"] == "1111111111"
