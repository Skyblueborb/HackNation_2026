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


def test_odwolanie_prompt_separates_header_and_action_dates() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_odwolanie.j2").read_text(
        encoding="utf-8"
    )
    for phrase in ("czynnosc_dzien", "pierwszego zarzutu", "Adresy"):
        assert phrase in template


def test_pelnomocnictwo_prompt_keeps_company_out_of_person_name() -> None:
    template = (REPO_ROOT / "configs/prompts/extract_pelnomocnictwo.j2").read_text(
        encoding="utf-8"
    )
    for phrase in ("osoba_prawna", "Nigdy nazwa firmy", "r. pr."):
        assert phrase in template


def test_odwolanie_spec_links_cause_to_action_sentence() -> None:
    spec = (REPO_ROOT / "configs/classes/odwolanie.yaml").read_text(encoding="utf-8")
    assert "przed pierwszym zarzutem" in spec
