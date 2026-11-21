"""classify_by_rules must reject foreign/negative documents, never force-fit
them into one of the three known classes just because a keyword happened to
match (procurement vocabulary like "zamawiając"/"postępowani" legitimately
appears in TED notices too, so score > 0 is not sufficient evidence).
"""

from __future__ import annotations

from pathlib import Path

from lab.llm.classify import classify_by_rules

# Excerpt of a real TED/eForms procurement notice (the one negative example
# shipped by the organizer). It contains odwolanie-ish keywords
# ("zamawiając"/"postępowani" show up in CPV/procedure boilerplate) but is
# not an odwolanie/pelnomocnictwo/przelew and must be rejected.
_TED_NOTICE_EXCERPT = """
364525-2025 - Procedura konkurencyjna See the notice on TED website
Polska - Serwery - Dostawa, wdrozenie, skonfigurowanie serwerowego srodowiska
teleinformatycznego wraz z serwisem i gwarancja
OJ S 107/2025 05/06/2025
Ogloszenie o zamowieniu lub ogloszenie o koncesji - tryb standardowy
1. Nabywca
1.1. Nabywca
Oficjalna nazwa: Narodowy Instytut Kardiologii
2. Procedura
2.1. Procedura
Identyfikator procedury: 49cc9072-820d-4a57-988e-7d086ec7f3fd
Rodzaj procedury: Otwarta w ramach postepowania o udzielenie zamowienia,
zamawiajacy przewiduje udzial wykonawcow zagranicznych.
"""


def test_ted_notice_is_rejected_not_odwolanie():
    assert classify_by_rules(Path("case1/anything.pdf"), _TED_NOTICE_EXCERPT) is None


def test_veto_overrides_a_misleading_filename():
    # Even if the file were (wrongly) named like an odwolanie, the content
    # marker must win.
    assert classify_by_rules(Path("odwolanie.pdf"), _TED_NOTICE_EXCERPT) is None


def test_real_classes_still_classify_by_filename_stem():
    assert classify_by_rules(Path("sprawa/odwolanie.pdf"), "") == "odwolanie"
    assert classify_by_rules(Path("sprawa/pelnomocnictwo.pdf"), "") == "pelnomocnictwo"
    assert (
        classify_by_rules(Path("sprawa/potwierdzenie_przelewu.pdf"), "")
        == "potwierdzenie_przelewu"
    )
    assert classify_by_rules(Path("sprawa/przelew.pdf"), "") == "potwierdzenie_przelewu"


def test_real_classes_still_classify_by_keyword_when_filename_is_arbitrary():
    text = "Odwołanie do Prezesa KIO na czynność Zamawiającego w postępowaniu."
    assert classify_by_rules(Path("case7/document.pdf"), text) == "odwolanie"


def test_unrecognized_text_without_veto_markers_is_also_rejected():
    assert classify_by_rules(Path("case9/mystery.pdf"), "Lorem ipsum dolor sit amet.") is None
