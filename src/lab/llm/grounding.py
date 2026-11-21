"""Post-extraction grounding and cross-field consistency.

Grounding only touches free-text string leaves: numbers, dates and enum
labels are validated/normalized elsewhere and must not be blanked because
their literal form in OCR differs from the normalized value.
"""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz, process

from o2jcore.normalize.values import normalize
from o2jcore.spec.models import DocClassSpec


def _targets(container: Any, segments: list[str]) -> list[tuple[dict, str]]:
    if not segments or not isinstance(container, dict):
        return []
    head, *rest = segments
    if head.endswith("[]"):
        key = head[:-2]
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
