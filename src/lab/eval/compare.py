"""Leaf-level verdicts: pred vs gold, after normalization.

`compare_leaf` handles the normal case, where gold describes the path (i.e.
there IS a gold leaf to compare against, even if its value is null). It does
NOT handle '!extra:' paths -- those have no gold counterpart by definition,
so callers (see `lab.eval.metrics.evaluate_run`) route them through a
simpler rule instead: non-null pred value under an unexpected key -> FP;
null -> skip entirely (never enters the counts).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from rapidfuzz import fuzz

from o2jcore.normalize.values import normalize


class Verdict(StrEnum):
    TP = "tp"
    FP = "fp"
    FN = "fn"
    FPFN = "fpfn"  # counts as BOTH one FP and one FN
    TN = "tn"


def compare_leaf(
    pred: Any, gold: Any, normalizer_name: str, *, mode: str, fuzzy_threshold: int = 90
) -> Verdict:
    """mode is 'exact' or 'fuzzy'. Both pred and gold are normalized first
    (normalizers are idempotent, so normalizing already-normalized gold is a
    no-op -- this just guards against gold that isn't perfectly normalized).
    """
    if mode not in ("exact", "fuzzy"):
        raise ValueError(f"compare_leaf: mode must be 'exact' or 'fuzzy', got {mode!r}")

    pred_n = normalize(normalizer_name, pred)
    gold_n = normalize(normalizer_name, gold)

    if pred_n is None and gold_n is None:
        return Verdict.TN
    if pred_n is not None and gold_n is None:
        return Verdict.FP
    if pred_n is None and gold_n is not None:
        return Verdict.FN

    # both non-null from here on
    if pred_n == gold_n:
        return Verdict.TP

    if mode == "exact":
        return Verdict.FPFN

    ratio = fuzz.ratio(str(pred_n), str(gold_n))
    return Verdict.TP if ratio >= fuzzy_threshold else Verdict.FPFN
