"""Document-class routing: deterministic filename/keyword rules first, with
an optional LLM fallback for the fourth `nieznany` class.
"""

from __future__ import annotations

import re
from pathlib import Path

from lab.llm.client import LLMClient, LLMResponse
from lab.llm.prompts import PromptSet

CLASSES = ("odwolanie", "pelnomocnictwo", "potwierdzenie_przelewu")
ALL_LABELS = (*CLASSES, "nieznany")

_STEMS = (
    ("odwolanie", "odwolanie"),
    ("pelnomocnictwo", "pelnomocnictwo"),
    ("potwierdzenie_przelewu", "potwierdzenie_przelewu"),
    ("przelew", "potwierdzenie_przelewu"),
)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "odwolanie": ("odwołanie", "odwolanie", "prezesa kio", "zamawiając", "zarzut", "postępowani"),
    "pelnomocnictwo": ("pełnomocnictwo", "pelnomocnictwo", "mocodawca", "umocowanie", "pełnomocnik"),
    "potwierdzenie_przelewu": ("przelew", "tytuł przelewu", "nadawca", "odbiorca", "rachunek"),
}


def classify_by_rules(pdf_path: Path, text: str) -> str | None:
    stem = Path(pdf_path).stem.lower()
    for needle, class_id in _STEMS:
        if needle in stem:
            return class_id

    lowered = text.lower()
    scores = {cid: sum(lowered.count(word) for word in words) for cid, words in _KEYWORDS.items()}
    best = max(scores.values(), default=0)
    if best == 0:
        return None
    winners = [cid for cid, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def _parse_label(text: str) -> str:
    lowered = text.strip().lower()
    match = re.search(r"\b(odwolanie|pelnomocnictwo|potwierdzenie_przelewu|nieznany)\b", lowered)
    return match.group(1) if match else "nieznany"


def classify_document(
    client: LLMClient | None,
    prompts: PromptSet,
    pdf_path: Path,
    text: str,
    method: str,
) -> tuple[str | None, LLMResponse | None]:
    predicted = classify_by_rules(pdf_path, text) if method in ("rules", "rules+llm") else None
    if predicted is not None or method == "rules":
        return predicted, None
    if client is None:
        raise ValueError("method 'llm' requires an LLM client")
    response = client.call_json(
        "Jesteś klasyfikatorem dokumentów. Odpowiadaj jednym słowem z listy: "
        + ", ".join(ALL_LABELS)
        + ".",
        prompts.classify(text),
        max_tokens=8,
    )
    label = _parse_label(response.text)
    return (None if label == "nieznany" else label), response
