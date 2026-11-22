"""Document routing: the keyword rules in isolation, and the hybrid on top.

Routing never consults the filename -- in the graded task it does not name the
document type -- so every case here is decided by content. A document foreign
to all three classes must be rejected by failing the thresholds, not by being
listed in a blocklist of known negatives.

`classify_by_keywords` is the rule layer on its own. `classify_with_evidence`
is what callers use: the trained centroids first, the rules only where the
model abstains.
"""

from __future__ import annotations

from lab.llm.classify import classify_by_keywords, classify_with_evidence

# Excerpt of a real TED/eForms procurement notice. It carries the procurement
# vocabulary that surrounds all three classes ("zamawiajacy", "postepowania")
# but none of their own markers, so it must score zero and be rejected.
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


def test_ted_notice_scores_zero_on_every_rule():
    result = classify_by_keywords(_TED_NOTICE_EXCERPT)
    assert result.label is None
    assert set(result.scores.values()) == {0.0}


def test_ted_notice_is_rejected_by_the_full_classifier():
    assert classify_with_evidence(_TED_NOTICE_EXCERPT).label is None


def test_unrecognized_text_is_rejected():
    assert classify_with_evidence("Lorem ipsum dolor sit amet.").label is None
    assert (
        classify_with_evidence("Faktura VAT nr 12/2026, kwota 1230 zl, termin 14 dni.").label
        is None
    )


def test_each_class_routes_on_its_own_markers():
    assert (
        classify_by_keywords(
            "Prezes Krajowej Izby Odwolawczej. Odwolujacy wnosi odwolanie i zarzut."
        ).label
        == "odwolanie"
    )
    assert (
        classify_by_keywords("PELNOMOCNICTWO. Mocodawca upowaznia pelnomocnika.").label
        == "pelnomocnictwo"
    )
    assert (
        classify_by_keywords(
            "Potwierdzenie przelewu. Platnik, beneficjent, tytul przelewu."
        ).label
        == "potwierdzenie_przelewu"
    )


def test_short_excerpt_is_routed_by_the_rules_when_the_model_abstains():
    """The model profiles a whole document, so an excerpt lands below its
    threshold. The rules carry exactly these cases."""
    result = classify_with_evidence("PELNOMOCNICTWO. Mocodawca upowaznia pelnomocnika.")
    assert result.label == "pelnomocnictwo"
    assert "ngram:abstain" in result.evidence


def test_letter_spaced_title_still_matches():
    """Legal titles are routinely letter-spaced, which defeats substring tests."""
    assert (
        classify_by_keywords(
            "P E L N O M O C N I C T W O\nMocodawca upowaznia pelnomocnika."
        ).label
        == "pelnomocnictwo"
    )


def test_missing_diacritics_still_match():
    """OCR output may drop Polish diacritics entirely."""
    with_diacritics = "PEŁNOMOCNICTWO. Mocodawca upoważnia pełnomocnika."
    without = "PELNOMOCNICTWO. Mocodawca upowaznia pelnomocnika."
    assert (
        classify_by_keywords(with_diacritics).label
        == classify_by_keywords(without).label
        == "pelnomocnictwo"
    )


def test_pelnomocnictwo_is_not_captured_by_the_appeal_it_authorises():
    """The regression that made a third of pelnomocnictwa route to odwolanie.

    A procedural power of attorney describes the appeal at length; only the
    appeal itself is addressed to the KIO in its own header.
    """
    text = (
        "Bydgoszcz, 2 marca 2026\n"
        "PELNOMOCNICTWO PROCESOWE\n"
        "Dzialajac w imieniu Wykonawcy, niniejszym upowazniam adw. Jana Kowalskiego "
        "do reprezentowania Wykonawcy w postepowaniu o udzielenie zamowienia "
        "publicznego oraz do wniesienia odwolania do Prezesa Krajowej Izby "
        "Odwolawczej i reprezentowania wobec Zamawiajacego."
    )
    assert classify_by_keywords(text).label == "pelnomocnictwo"
    assert classify_with_evidence(text).label == "pelnomocnictwo"


def test_ambiguous_text_without_a_clear_winner_is_rejected():
    assert classify_by_keywords("odwolanie przelew").label is None
    assert classify_with_evidence("odwolanie przelew").label is None
