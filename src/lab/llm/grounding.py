"""Post-extraction grounding and cross-field consistency.

Grounding only touches free-text string leaves: numbers, dates and enum
labels are validated/normalized elsewhere and must not be blanked because
their literal form in OCR differs from the normalized value.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz, process

from o2jcore.normalize import parse_date_pl
from o2jcore.normalize.values import normalize
from o2jcore.spec.models import DocClassSpec, split_segment


def _targets(container: Any, segments: list[str]) -> list[tuple[dict, str]]:
    if not segments or not isinstance(container, dict):
        return []
    head, *rest = segments
    key, is_list = split_segment(head)
    if is_list:
        items = container.get(key)
        if not isinstance(items, list):
            return []
        out: list[tuple[dict, str]] = []
        for item in items:
            out.extend(_targets(item, rest))
        return out
    child = container.get(head)
    if not rest:
        return [(container, head)] if isinstance(child, (str, int, float, type(None))) else []
    return _targets(child, rest)


def ground_object(obj: dict, spec: DocClassSpec, text: str, *, threshold: int = 85) -> int:
    """Set free-text leaves not grounded in OCR to None. Returns how many."""
    lines = [
        str(normalize("text", line) or "")
        for line in text.splitlines()
        if len(line.strip()) >= 3
    ][:1500]
    lines = [line for line in lines if line]

    nulled = 0
    for field in spec.fields:
        if (
            field.kind != "string"
            or field.normalizer not in ("text", "name")
            or field.derived_from is not None
            or not lines
        ):
            continue
        for container, key in _targets(obj, field.segments):
            value = container.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            match = process.extractOne(value, lines, scorer=fuzz.partial_ratio, score_cutoff=threshold)
            if match is None:
                container[key] = None
                nulled += 1
    return nulled


_HEADER_PATHS = ("OdwolanieKIO.miejscowosc", "OdwolanieKIO.data")
# The line sits anywhere in the opening block -- after the KIO address and the
# parties, as late as line 30. Exactly one line per document matches, so the
# first hit is the header.
_HEADER_SCAN_LINES = 60
# "Katowice, dnia 24 sierpnia 2026 roku" / "Kielce, dnia 29.09.2026 roku". The
# city is one to three capitalised words, so an address line ("ul. Topolowa 79,
# 85-512 Bydgoszcz") cannot pose as one.
_HEADER_RE = re.compile(
    r"^([A-ZŁŚŻĆÓĘĄŃ][\w-]+(?:[ -][A-ZŁŚŻĆÓĘĄŃ][\w-]+){0,2}),\s*"
    r"(?:dnia\s+)?(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}|\d{1,2}\s+[a-ząćęłńóśźż]+\s+\d{4})"
    r"\s*(?:roku|r\.)?\s*$"
)

# Each party's identifiers sit in its own header block, under the role label.
# The label is matched on the role word alone, not on a following colon: it can
# carry a parenthetical that wraps the colon onto the next line ("Zamawiający
# (zamawiający wspólnie przeprowadzający postępowanie na podstawie art. 38 …)").
# Body sentences opening with the same word therefore reopen the block, which is
# harmless -- lines append to the one list per role, and only the first
# identifier line in it is read, so the header line always wins.
_PARTY_SECTIONS: tuple[tuple[str, str], ...] = (
    (r"^Odwołując(?:y|a)\b", "Odwolujacy[]"),
    (r"^Zamawiając(?:y|a)\b", "Zamawiajacy[]"),
)
_PARTY_ID_RES = {
    "krs": re.compile(r"\bKRS\b[:\s]*(\d{10})(?!\d)"),
    "nip": re.compile(r"\bNIP\b[:\s]*(\d{10})(?!\d)"),
    "regon": re.compile(r"\bREGON\b[:\s]*(\d{9}|\d{14})(?!\d)"),
}
_SECTION_BREAK_RE = re.compile(
    r"^(?:Odwołując|Zamawiając|Prezes\b|ODWOŁANIE|dotyczy\s*:|Działając\b)"
)

_CZYNNOSC_PATH = "OdwolanieKIO.czynnosc_powod_id"
_CZYNNOSC_START_RE = re.compile(r"Zamawiający\s+w\s+dniu\b")
_CZYNNOSC_STOP_RE = re.compile(r"Zarzut\s+nr|Zaskarżonym\s+czynnościom|Ad\.\s*zarzutu")
# The challenged act is the first sentence; later sentences recount the earlier
# history of the same procurement ("Następnie … dokonał modyfikacji treści SWZ")
# and would outvote it. A period only ends the sentence when an upper-case word
# follows, which leaves "sp. z o.o." and "nr 14/INW/2022" intact.
_SENTENCE_END_RE = re.compile(r"\.\s+(?=[A-ZŁŚŻĆÓĘĄŃ])")
# Ordered: every omission pattern is tested before the positive verb it
# contains, because "zaniechał unieważnienia" also matches "unieważni...".
# \w{0,3} after a verb stem absorbs OCR doubling ("unieważniił").
_CZYNNOSC_RULES: tuple[tuple[int, str], ...] = (
    (10, r"nie\s+unieważni\w*|zaniecha\w*\s+unieważnienia"),
    (8, r"nie\s+wykluczy\w*|zaniecha\w*\s+wykluczenia"),
    (7, r"nie\s+odrzuci\w*|zaniecha\w*\s+odrzucenia"),
    (6, r"odpowiedzi\s+i\s+wyjaśnienia|wyjaśnieni\w+\s+(?:do\s+)?treści|udzieli\w+\s+odpowiedzi"),
    (5, r"(?:zmieni\w+|zmodyfikowa\w+|modyfikacj\w+)[^.]{0,60}(?:SWZ|Specyfikacj)"),
    (11, r"[Oo]pis\w*\s+[Pp]rzedmiotu\s+[Zz]amówienia|\bOPZ\b"),
    (4, r"(?:opublikowa\w+|udostępni\w+|zamieści\w+)[^.]{0,120}(?:Specyfikacj|SWZ)"),
    (9, r"unieważni\w{0,3}\s+postępowanie"),
    (3, r"wyklucz\w+"),
    (1, r"odrzuc\w+[^.]{0,60}ofert|o\s+odrzuceniu\s+ofert"),
    (2, r"wyb\w+[^.]{0,60}ofert"),
)


def enforce_header(obj: dict, spec: DocClassSpec, text: str) -> int:
    """Fill `miejscowosc` and `data` from the "Miejscowość, dnia …" header line.

    Both are null in the LLM's output far more often than they are absent: the
    line is always in the opening block, always in this one shape, and the long
    prompt paragraph warning against address lines pushes the model to null
    instead. A regex has no such hesitation.

    Authoritative where it matches, unlike `enforce_party_ids`: across all 60
    gold odwołania exactly one line per document matches, and it agrees with
    gold every time, so the match beats the model's answer -- including the
    model's other failure here, returning the whole line as the city. A
    document with no such line is left to the model.
    """
    by_path = {field.path: field for field in spec.fields}
    if not any(path in by_path for path in _HEADER_PATHS):
        return 0

    found: tuple[str, str] | None = None
    for line in text.splitlines()[:_HEADER_SCAN_LINES]:
        match = _HEADER_RE.match(line.strip())
        if match is not None:
            found = (match.group(1), match.group(2))
            break
    if found is None:
        return 0
    city, raw_date = found

    filled = 0
    for path, value in (
        ("OdwolanieKIO.miejscowosc", city),
        ("OdwolanieKIO.data", parse_date_pl(raw_date)),
    ):
        field = by_path.get(path)
        if field is None or value is None:
            continue
        for container, key in _targets(obj, field.segments):
            if container.get(key) != value:
                container[key] = value
                filled += 1
    return filled


def _party_blocks(text: str) -> dict[str, str]:
    """Split the header into one text block per party role."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        matched = next(
            (prefix for pattern, prefix in _PARTY_SECTIONS if re.match(pattern, stripped)),
            None,
        )
        if matched is not None:
            current = matched
            blocks.setdefault(current, [])
            continue
        if current is None:
            continue
        if _SECTION_BREAK_RE.match(stripped):
            current = None
            continue
        blocks[current].append(stripped)
    return {prefix: "\n".join(lines) for prefix, lines in blocks.items()}


def enforce_party_ids(obj: dict, spec: DocClassSpec, text: str) -> int:
    """Fill a party's null KRS/NIP/REGON from the labelled line in its own block.

    The identifiers arrive as one line per party ("KRS: …, NIP: …, REGON: …"),
    yet the LLM drops the KRS while keeping its two neighbours. Reading the
    label is not a judgement call, so it should not be asked of the model.

    Only the first such line in a block is read. A block can go on to list
    consortium partners or a chosen bidder, each with identifiers of their own,
    and the party's own line always comes first -- which is also the spec's rule
    for a consortium: the leader's numbers stand for the whole. A value the
    model already produced is never overwritten; a wrong non-null value means
    corrupted input, which belongs to the text-layer gate, not here.
    """
    by_path = {field.path: field for field in spec.fields}
    filled = 0
    for prefix, block in _party_blocks(text).items():
        line = next(
            (
                line
                for line in block.splitlines()
                if any(pattern.search(line) for pattern in _PARTY_ID_RES.values())
            ),
            None,
        )
        if line is None:
            continue
        for name, pattern in _PARTY_ID_RES.items():
            field = by_path.get(f"{prefix}.{name}")
            match = pattern.search(line)
            if field is None or match is None:
                continue
            for container, key in _targets(obj, field.segments):
                if container.get(key) is None:
                    container[key] = match.group(1)
                    filled += 1
    return filled


def _czynnosc_window(text: str, limit: int = 400) -> str | None:
    """The one sentence naming the challenged act."""
    match = _CZYNNOSC_START_RE.search(text)
    if match is None:
        return None
    window = text[match.start() : match.start() + limit]
    for cut in (_SENTENCE_END_RE.search(window), _CZYNNOSC_STOP_RE.search(window)):
        if cut is not None:
            window = window[: cut.start()]
    return window


def enforce_czynnosc(obj: dict, spec: DocClassSpec, text: str) -> bool:
    """Set the dictionary id from the sentence describing the challenged act.

    This is the one field the LLM gets wrong in a regular way: it finds the
    right sentence (czynnosc_dzien is correct in every observed miss) but drops
    the negation, scoring "nie wykluczył" as 3 ("Decyzja o wykluczeniu")
    instead of 8 ("Zaniechanie wykluczenia"). The phrase is formulaic, so a
    table beats the model here. A sentence no pattern matches keeps the LLM's
    answer. `czynnosc_opis` follows via `enforce_derived`, so call this first.
    """
    field = next((f for f in spec.fields if f.path == _CZYNNOSC_PATH), None)
    if field is None:
        return False
    window = _czynnosc_window(text)
    if window is None:
        return False
    for value, pattern in _CZYNNOSC_RULES:
        if not re.search(pattern, window):
            continue
        for container, key in _targets(obj, field.segments):
            if container.get(key) != value:
                container[key] = value
                return True
        return False
    return False


def enforce_derived(obj: dict, spec: DocClassSpec) -> int:
    """Fill fields with `derived_from` from their source field's enum map."""
    by_path = {field.path: field for field in spec.fields}
    filled = 0
    for field in spec.fields:
        if field.derived_from is None:
            continue
        source = by_path.get(field.derived_from)
        if source is None or source.enum is None or source.enum.values is None:
            continue
        sources = _targets(obj, source.segments)
        targets = _targets(obj, field.segments)
        for (source_container, source_key), (target_container, target_key) in zip(sources, targets):
            value = source_container.get(source_key)
            try:
                key = int(value)
            except (TypeError, ValueError):
                continue
            label = source.enum.values.get(key)
            if label is not None and target_container.get(target_key) != label:
                target_container[target_key] = label
                filled += 1
    return filled
