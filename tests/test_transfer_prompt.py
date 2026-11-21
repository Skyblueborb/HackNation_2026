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
