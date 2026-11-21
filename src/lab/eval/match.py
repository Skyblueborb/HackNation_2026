"""Element-wise similarity and greedy alignment for list-of-object fields.

Used only to decide *which* pred element corresponds to *which* gold
element before scoring happens -- the actual TP/FP/FN/FPFN accounting is
done later, after alignment, via normal leaf comparison (see
`lab.eval.compare`).
"""

from __future__ import annotations

from o2jcore.spec.models import FieldSpec, ListSpec
from rapidfuzz import fuzz

from lab.eval.flatten import flatten_fields


def element_similarity(
    pred_elem: dict, gold_elem: dict, list_spec: ListSpec, field_specs: dict[str, FieldSpec]
) -> float:
    """Similarity in [0, 1] between one predicted list element and one gold
    list element. Leaves that are null on BOTH sides are excluded from the
    denominator; `list_spec.match_on` fields get 3x weight; zero comparable
    leaves -> 0.0 (never NaN, never 1.0)."""
    fields = list(field_specs.values())
    pred_flat = flatten_fields(
        pred_elem if isinstance(pred_elem, dict) else {}, fields, prefix_extra=False
    )
    gold_flat = flatten_fields(
        gold_elem if isinstance(gold_elem, dict) else {}, fields, prefix_extra=False
    )
    all_paths = set(pred_flat) | set(gold_flat)
    match_on_keys = set(list_spec.match_on)

    total_weight = 0.0
    weighted_sum = 0.0
    for path in all_paths:
        pv = pred_flat.get(path)
        gv = gold_flat.get(path)
        if pv is None and gv is None:
            continue  # excluded from denominator

        if pv == gv:
            score = 1.0
        else:
            score = fuzz.ratio(str(pv), str(gv)) / 100.0

        final_key = path.split(".")[-1].split("[")[0]
        weight = 3.0 if final_key in match_on_keys else 1.0
        total_weight += weight
        weighted_sum += weight * score

    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight


def greedy_align(
    pred_list: list[dict],
    gold_list: list[dict],
    list_spec: ListSpec,
    field_specs: dict[str, FieldSpec],
) -> list[tuple[int | None, int | None]]:
    """Greedily pair pred/gold indices in descending similarity order, each
    index used at most once, skipping zero-score pairs entirely. Unmatched
    gold indices -> (None, gold_idx); unmatched pred indices -> (pred_idx,
    None). Output is ordered by gold index ascending, with purely-spurious
    pred-only entries (no gold counterpart) appended at the end."""
    n_pred = len(pred_list)
    n_gold = len(gold_list)

    scored: list[tuple[float, int, int]] = []
    for pi in range(n_pred):
        for gi in range(n_gold):
            s = element_similarity(pred_list[pi], gold_list[gi], list_spec, field_specs)
            if s > 0.0:
                scored.append((s, pi, gi))

    # Descending score; stable, deterministic tie-break by (pred_idx, gold_idx).
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_pred: set[int] = set()
    used_gold: set[int] = set()
    gold_to_pred: dict[int, int] = {}
    for _score, pi, gi in scored:
        if pi in used_pred or gi in used_gold:
            continue
        used_pred.add(pi)
        used_gold.add(gi)
        gold_to_pred[gi] = pi

    result: list[tuple[int | None, int | None]] = []
    for gi in range(n_gold):
        result.append((gold_to_pred.get(gi), gi))
    for pi in range(n_pred):
        if pi not in used_pred:
            result.append((pi, None))
    return result
