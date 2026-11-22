"""Guard for the account-number mapping in the transfer confirmation prompt."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO_ROOT / "configs" / "prompts" / "extract_potwierdzenie_przelewu.j2"


def test_prompt_spells_out_account_mapping() -> None:
    template = PROMPT_PATH.read_text(encoding="utf-8")

    for phrase in (
        "z_rachunku",
        "na_rachunek",
        "Rachunek obciążany",
        "Rachunek odbiorcy",
    ):
        assert phrase in template, f"Brak mapowania konta w promptach: {phrase}"


def test_global_rules_prefer_null_over_guessing() -> None:
    template = (REPO_ROOT / "configs/prompts/rules.j2").read_text(encoding="utf-8")
    for phrase in ("W razie wątpliwości", "null", "Nie kopiuj"):
        assert phrase in template


def test_global_rules_limit_null_to_strict_values() -> None:
    template = (REPO_ROOT / "configs/prompts/rules.j2").read_text(encoding="utf-8")
    assert "Dotyczy wartości ścisłych" in template
    assert "nie zamieniaj wyraźnej wartości na null" in template


def test_odwolanie_prompt_separates_header_and_action_dates() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "czynnosc_dzien",
        "pierwszego zarzutu",
        "Adresy",
        "Adres Prezesa KIO",
        "unieważnił",
        "kancelarii",
        "numer referencyjny",
        "Nie przepisuj NIP ani REGON",
        "Nie składaj miejscowości",
        "późniejszych",
    ):
        assert phrase in template


def test_odwolanie_prompt_accepts_month_names_for_header_date() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    assert "nazwę miesiąca" in template
    assert "Nigdy daty nagłówka" in template


def test_odwolanie_prompt_excludes_opz_from_reasons() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    assert "OPZ w treści zarzutów" in template


def test_odwolanie_prompt_explains_zaniechanie() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    assert "zaniechanie" in template.lower()
    assert "nie wykluczył" in template


def test_odwolanie_prompt_lists_every_enum_label() -> None:
    enum = (REPO_ROOT / "configs/enums/czynnosc_powod.yaml").read_text(
        encoding="utf-8"
    )
    labels = [
        line.split('"', 2)[1]
        for line in enum.splitlines()
        if line and line[0].isdigit() and '"' in line
    ]
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    assert len(labels) == 11
    for label in labels:
        assert label in template, f"Brak etykiety w promptach: {label}"


def test_odwolanie_prompt_has_negative_locality_example() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    assert "NIE jest miejscowością" in template


def test_transfer_prompt_requires_full_title() -> None:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    assert "nie skracaj" in template
    assert "kończy się numerem transakcji" in template


def test_pelnomocnictwo_prompt_keeps_company_out_of_person_name() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_pelnomocnictwo.j2").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "osoba_prawna",
        "Nigdy nazwa firmy",
        "r. pr.",
        "Podpisano",
        "Null tylko wtedy",
        "nie do `podpisujacy[]`",
        "kropkową linią",
    ):
        assert phrase in template


def test_odwolanie_spec_links_cause_to_action_sentence() -> None:
    spec = (REPO_ROOT / "configs/classes/odwolanie.yaml").read_text(encoding="utf-8")
    assert "przed pierwszym zarzutem" in spec
