"""Document-class routing from OCR text alone.

The filename is never consulted: in the graded task the PDFs carry opaque
names, so any routing that leans on the stem scores well on the dev set (where
files are literally `odwolanie.pdf`) and collapses on the real one.

Routing is deterministic weighted keyword scoring with three corrections over
a plain substring count:

* **Diacritic folding** so one spelling of a marker matches both the clean
  text and OCR output that dropped the Polish diacritics.
* **Whitespace-stripped matching**, because legal titles are routinely
  letter-spaced for emphasis (`P E Ł N O M O C N I C T W O`), which defeats a
  plain substring test.
* **Header weighting**, because a Polish pleading names its own type in the
  opening block, while the *other* document types it merely refers to appear
  further down the body. A pelnomocnictwo granting the power to file an
  appeal talks about the appeal at length; only the appeal itself is addressed
  to the KIO in its header.

Acceptance needs positive evidence: a winning score above `MIN_SCORE` that
also beats the runner-up by `MARGIN`. Everything else is `None` (rejected),
so documents foreign to all three classes fail by default rather than needing
to be enumerated in a blocklist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lab.llm.client import LLMClient, LLMResponse
from lab.llm.ngram import CentroidModel
from lab.llm.prompts import PromptSet
from lab.paths import REPO_ROOT

# Trained centroids ship with the repo; `lab train-classifier` rebuilds them.
MODEL_PATH = REPO_ROOT / "configs" / "classifier" / "centroids.npz"

CLASSES = ("odwolanie", "pelnomocnictwo", "potwierdzenie_przelewu")
ALL_LABELS = (*CLASSES, "nieznany")

# A pleading declares its type in the opening block: a title line, or the
# addressee/parties header. Markers found here are worth HEADER_BONUS extra.
HEADER_CHARS = 400
HEADER_BONUS = 3.0

# A marker repeated across a long document must not outweigh a decisive marker
# in a short one, so each marker's count is capped before weighting.
MAX_HITS = 3

# Accept only on positive evidence: a clear winner, clearly ahead.
MIN_SCORE = 3.0
MARGIN = 1.5

_STRONG = 3.0
_WEAK = 1.0

# Markers are written folded (no diacritics) and lowercase; see _fold.
#
# Down-weighting the forum markers ("krajowej izby odwolawczej", "prezesa
# kio") outside the header was tried and measured: it cost accuracy in every
# degraded scenario, because dropping the opening block just promotes the next
# 400 characters to header. Position is carried by HEADER_BONUS alone.
#
# Deliberately absent: "zamawiajac" and "postepowani". They describe the
# public-procurement setting shared by all three classes -- a pelnomocnictwo
# authorises action "w postepowaniu o udzielenie zamowienia" and a transfer
# pays a fee in one -- so they are context, not evidence, and counting them
# for odwolanie is what made a third of pelnomocnictwa route there.
_MARKERS: dict[str, tuple[tuple[str, float], ...]] = {
    "odwolanie": (
        ("krajowej izby odwolawczej", _STRONG),
        ("prezesa kio", _STRONG),
        ("odwolujacy", _STRONG),
        ("wnosze odwolanie", _STRONG),
        ("zarzut", _WEAK),
        ("odwolanie", _WEAK),
    ),
    "pelnomocnictwo": (
        ("pelnomocnictwo", _STRONG),
        ("mocodawca", _STRONG),
        ("upowazniam", _STRONG),
        ("ustanawiam pelnomocnikiem", _STRONG),
        ("umocowanie", _STRONG),
        ("pelnomocnik", _WEAK),
    ),
    "potwierdzenie_przelewu": (
        ("polecenie przelewu", _STRONG),
        ("potwierdzenie przelewu", _STRONG),
        ("potwierdzenie transakcji", _STRONG),
        ("potwierdzenie realizacji", _STRONG),
        ("dowod wykonania przelewu", _STRONG),
        ("rachunek obciazany", _STRONG),
        ("zleceniodawca", _STRONG),
        ("beneficjent", _STRONG),
        ("platnik", _STRONG),
        ("tytul przelewu", _STRONG),
        ("nadawca", _WEAK),
        ("odbiorca", _WEAK),
        ("rachunek", _WEAK),
        ("przelew", _WEAK),
    ),
}

_DIACRITICS = str.maketrans("ąćęłńóśźż", "acelnoszz")
_WHITESPACE = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Lowercase and strip Polish diacritics so one marker spelling suffices."""
    return text.lower().translate(_DIACRITICS)


def _despace(text: str) -> str:
    """Drop whitespace so letter-spaced titles match a plain marker."""
    return _WHITESPACE.sub("", text)


@dataclass(frozen=True)
class Classification:
    """A routing decision with the evidence behind it.

    `label` is None when the document is rejected. `scores` and `evidence`
    explain the call, for logging and for deciding whether to escalate to the
    LLM fallback.
    """

    label: str | None
    scores: dict[str, float]
    evidence: tuple[str, ...]

    @property
    def margin(self) -> float:
        """How far the winner is ahead of the runner-up (inf when alone)."""
        ranked = sorted(self.scores.values(), reverse=True)
        if not ranked or ranked[0] == 0:
            return 0.0
        runner_up = ranked[1] if len(ranked) > 1 else 0.0
        return float("inf") if runner_up == 0 else ranked[0] / runner_up


def _score_class(
    markers: tuple[tuple[str, float], ...],
    body: str,
    header: str,
    body_despaced: str,
    header_despaced: str,
) -> tuple[float, list[str]]:
    total = 0.0
    found: list[str] = []
    for marker, weight in markers:
        marker_despaced = _despace(marker)
        hits = max(body.count(marker), body_despaced.count(marker_despaced))
        if not hits:
            continue
        total += weight * min(hits, MAX_HITS)
        in_header = marker in header or marker_despaced in header_despaced
        if in_header:
            total += weight * HEADER_BONUS
        found.append(f"{marker}x{hits}{'^' if in_header else ''}")
    return total, found


@cache
def _model() -> CentroidModel | None:
    """Load the trained centroids once, or None when they are not built yet."""
    if not MODEL_PATH.exists():
        return None
    return CentroidModel.load(MODEL_PATH)


def classify_with_evidence(text: str) -> Classification:
    """Route with the trained model, and ask the keyword rules when it abstains.

    The model beats the rules on every degraded full document (see
    lab.llm.ngram), but it compares a whole-document n-gram profile, so a
    short excerpt is unlike any centroid and scores below the threshold. The
    rules have the opposite shape: one decisive phrase is enough for them.
    Running the rules on exactly the cases the model declines keeps both
    strengths, and a document neither can place is still rejected.
    """
    model = _model()
    if model is None:
        return classify_by_keywords(text)

    label, scores = model.predict(text)
    if label is not None:
        return Classification(label, scores, (f"ngram:{label}@{scores[label]:.3f}",))

    fallback = classify_by_keywords(text)
    if fallback.label is None:
        return Classification(None, scores, ())
    return Classification(
        fallback.label,
        scores,
        ("ngram:abstain", *fallback.evidence),
    )


def classify_by_keywords(text: str) -> Classification:
    """Score every class and accept only a clear, sufficiently strong winner."""
    body = _fold(text)
    header = body[:HEADER_CHARS]
    body_despaced = _despace(body)
    header_despaced = _despace(header)

    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for class_id, markers in _MARKERS.items():
        score, found = _score_class(markers, body, header, body_despaced, header_despaced)
        scores[class_id] = score
        evidence[class_id] = found

    winner = max(scores, key=lambda cid: scores[cid])
    best = scores[winner]
    runner_up = max((s for cid, s in scores.items() if cid != winner), default=0.0)

    accepted = best >= MIN_SCORE and (runner_up == 0 or best >= runner_up * MARGIN)
    label = winner if accepted else None
    return Classification(label, scores, tuple(evidence[winner]) if accepted else ())


def classify_by_rules(text: str) -> str | None:
    """Deterministic routing from text; None when the evidence is too weak."""
    return classify_with_evidence(text).label


def _parse_label(text: str) -> str:
    lowered = text.strip().lower()
    match = re.search(r"\b(odwolanie|pelnomocnictwo|potwierdzenie_przelewu|nieznany)\b", lowered)
    return match.group(1) if match else "nieznany"


def classify_document(
    client: LLMClient | None,
    prompts: PromptSet,
    text: str,
    method: str,
) -> tuple[str | None, LLMResponse | None]:
    predicted = classify_by_rules(text) if method in ("rules", "rules+llm") else None
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
