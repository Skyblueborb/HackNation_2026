"""Aggregated counts, precision/recall/F1, and the top-level evaluation
driver that walks a run directory against gold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from o2jcore.spec.models import DocClassSpec

from lab.eval.compare import Verdict, compare_leaf
from lab.eval.flatten import canonicalize_path, flatten_pair

_MODES = ("exact", "fuzzy")
_NULL_POLICIES = ("skip", "tp", "strict")


@dataclass(slots=True)
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, verdict: Verdict) -> None:
        if verdict == Verdict.TP:
            self.tp += 1
        elif verdict == Verdict.FP:
            self.fp += 1
        elif verdict == Verdict.FN:
            self.fn += 1
        elif verdict == Verdict.TN:
            self.tn += 1
        elif verdict == Verdict.FPFN:
            self.fp += 1
            self.fn += 1
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown verdict: {verdict!r}")

    def precision_recall_f1(self, null_policy: str) -> tuple[float, float, float]:
        """null_policy in {'skip', 'tp', 'strict'}.

        'skip' (and 'strict', an alias of it at this level -- see below):
          P = tp / (tp + fp); zero-denominator convention: if tp+fp == 0,
          precision is undefined by the raw formula, so by convention we
          return 1.0 when fn == 0 too (nothing predicted, nothing missed --
          vacuously perfect) and 0.0 otherwise (nothing predicted, but
          something *was* missed).
          R = tp / (tp + fn); analogous convention: if tp+fn == 0 (nothing
          in gold to find), return 1.0 if fp == 0 (nothing spuriously
          predicted either) else 0.0.
          F1 = 2PR / (P+R) if P+R > 0 else 0.0.

        'tp': identical formulas, but tn is folded in as additional true
          positives (both-null leaves count as "correctly predicted
          absent"): P = (tp+tn)/(tp+tn+fp), R = (tp+tn)/(tp+tn+fn), same
          zero-denominator conventions (substituting tp+tn for tp).

        'strict': the real distinction between 'skip' and 'strict' is meant
          to live at a higher aggregation level than this dataclass -- e.g.
          a field marked "required" in some future field-requiredness
          metadata should have its tn treated as a penalty (an omission
          masquerading as a true negative) rather than ignored. No such
          requiredness metadata exists yet in A4, so there is nothing for
          'strict' to do differently here; it is implemented as a literal
          alias of 'skip' and this comment is the hook for that future
          escalation.
        """
        if null_policy not in _NULL_POLICIES:
            raise ValueError(f"unknown null_policy: {null_policy!r}")

        if null_policy == "tp":
            tp_eff = self.tp + self.tn
        else:  # 'skip' or 'strict' (alias, see docstring)
            tp_eff = self.tp

        fp = self.fp
        fn = self.fn

        denom_p = tp_eff + fp
        if denom_p == 0:
            precision = 1.0 if fn == 0 else 0.0
        else:
            precision = tp_eff / denom_p

        denom_r = tp_eff + fn
        if denom_r == 0:
            recall = 1.0 if fp == 0 else 0.0
        else:
            recall = tp_eff / denom_r

        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0

        return precision, recall, f1


def _empty_counts_map() -> dict[str, Counts]:
    return {mode: Counts() for mode in _MODES}


@dataclass
class EvalResult:
    overall: dict[str, Counts] = field(default_factory=_empty_counts_map)
    per_class: dict[str, dict[str, Counts]] = field(default_factory=dict)
    per_field: dict[str, dict[str, Counts]] = field(default_factory=dict)
    per_file: dict[str, dict[str, Counts]] = field(default_factory=dict)
    classification: dict[str, dict[str, int]] = field(default_factory=dict)
    reject: Counts = field(default_factory=Counts)
    invalid_json: int = 0
    retries: int = 0
    missing_pred: int = 0
    n_files_evaluated: int = 0
    mismatches: list[dict[str, Any]] = field(default_factory=list)


def _add_verdict(
    result: EvalResult,
    cid: str,
    rel_path: str,
    field_key: str,
    mode: str,
    verdict: Verdict,
    file_counts: dict[str, Counts],
) -> None:
    result.overall[mode].add(verdict)
    result.per_class.setdefault(cid, _empty_counts_map())[mode].add(verdict)
    result.per_field.setdefault(field_key, _empty_counts_map())[mode].add(verdict)
    file_counts[mode].add(verdict)


def evaluate_run(
    pred_dir: Path,
    gold_dir: Path,
    specs: dict[str, DocClassSpec],
    set_ids: list[str] | None = None,
) -> EvalResult:
    """Evaluate predictions in `pred_dir` against gold in `gold_dir` for each
    of the 3 document classes, across every set in `set_ids` (or every
    `przyklad_*` directory found under `gold_dir` when `set_ids` is None).

    For the Phase A identity sanity check, call this with
    `pred_dir == gold_dir`.

    Classification/reject-detection: no classifier exists yet in this phase
    (that's a later phase's job -- wiring it in is NOT in scope for A4). For
    every file found, this function simply records it as "correctly
    classified as its own class, not rejected" so `classification` and
    `reject` are shaped correctly and ready for a real classifier to feed
    into later.
    """
    pred_dir = Path(pred_dir)
    gold_dir = Path(gold_dir)

    if set_ids is None:
        set_dirs = sorted(
            (p for p in gold_dir.glob("przyklad_*") if p.is_dir()),
            key=lambda p: int(p.name.split("_")[1]),
        )
        set_ids = [p.name for p in set_dirs]

    result = EvalResult()

    for set_id in set_ids:
        for cid, spec in specs.items():
            gold_path = gold_dir / set_id / f"{spec.gold_stem}.json"
            if not gold_path.exists():
                continue

            rel_path = f"{set_id}/{spec.gold_stem}.json"
            gold_obj = json.loads(gold_path.read_text(encoding="utf-8"))

            pred_path = pred_dir / set_id / f"{spec.gold_stem}.json"
            pred_obj: dict = {}
            if not pred_path.exists():
                result.missing_pred += 1
            else:
                raw = pred_path.read_bytes()
                if len(raw) == 0:
                    result.invalid_json += 1
                else:
                    try:
                        pred_obj = json.loads(raw.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        result.invalid_json += 1
                        pred_obj = {}
                    if not isinstance(pred_obj, dict):
                        pred_obj = {}

            pred_flat, gold_flat = flatten_pair(pred_obj, gold_obj, spec)

            file_counts = _empty_counts_map()

            extra_pred_paths = {
                p for p in pred_flat if p.startswith("!extra:") and pred_flat[p] is not None
            }
            all_paths = set(gold_flat.keys()) | extra_pred_paths

            field_by_path = {f.path: f for f in spec.fields}

            for path in all_paths:
                field_key = canonicalize_path(path)

                if path.startswith("!extra:"):
                    pred_val = pred_flat.get(path)
                    gold_val = None
                    for mode in _MODES:
                        _add_verdict(result, cid, rel_path, field_key, mode, Verdict.FP, file_counts)
                    result.mismatches.append(
                        {
                            "file": rel_path,
                            "field": field_key,
                            "expected": gold_val,
                            "got": pred_val,
                            "verdict": str(Verdict.FP),
                        }
                    )
                    continue

                gold_val = gold_flat.get(path)
                pred_val = pred_flat.get(path)
                fspec = field_by_path.get(field_key)
                normalizer_name = fspec.normalizer if fspec is not None else "identity"

                for mode in _MODES:
                    verdict = compare_leaf(pred_val, gold_val, normalizer_name, mode=mode)
                    _add_verdict(result, cid, rel_path, field_key, mode, verdict, file_counts)
                    if mode == "exact" and verdict not in (Verdict.TP, Verdict.TN):
                        result.mismatches.append(
                            {
                                "file": rel_path,
                                "field": field_key,
                                "expected": gold_val,
                                "got": pred_val,
                                "verdict": str(verdict),
                            }
                        )

            result.per_file[rel_path] = file_counts
            result.n_files_evaluated += 1

            # Classification / reject wiring is out of scope for A4 -- no
            # classifier exists yet. Trivially record "correctly classified
            # as its own class, not rejected" so downstream shapes exist.
            result.classification.setdefault(cid, {}).setdefault(cid, 0)
            result.classification[cid][cid] += 1
            result.reject.add(Verdict.TP)

    return result


def _counts_to_dict(counts: Counts) -> dict[str, Any]:
    out: dict[str, Any] = {"tp": counts.tp, "fp": counts.fp, "fn": counts.fn, "tn": counts.tn}
    for policy in _NULL_POLICIES:
        p, r, f1 = counts.precision_recall_f1(policy)
        out[f"precision_{policy}"] = p
        out[f"recall_{policy}"] = r
        out[f"f1_{policy}"] = f1
    return out


def write_metrics(result: EvalResult, out_path: Path) -> None:
    """Serialize an EvalResult to metrics.json: flat, readable dicts with
    raw counts plus precision/recall/f1 under all three null_policy views,
    per mode, at the overall/per_class/per_field levels. per_file keeps raw
    counts only (no P/R/F1), to keep the file from ballooning on large
    runs."""
    out_path = Path(out_path)

    payload: dict[str, Any] = {
        "n_files_evaluated": result.n_files_evaluated,
        "invalid_json": result.invalid_json,
        "retries": result.retries,
        "missing_pred": result.missing_pred,
        "overall": {mode: _counts_to_dict(result.overall[mode]) for mode in _MODES},
        "per_class": {
            cid: {mode: _counts_to_dict(counts_map[mode]) for mode in _MODES}
            for cid, counts_map in sorted(result.per_class.items())
        },
        "per_field": {
            fkey: {mode: _counts_to_dict(counts_map[mode]) for mode in _MODES}
            for fkey, counts_map in sorted(result.per_field.items())
        },
        "per_file": {
            fpath: {mode: {"tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn} for mode, c in counts_map.items()}
            for fpath, counts_map in sorted(result.per_file.items())
        },
        "classification": result.classification,
        "reject": _counts_to_dict(result.reject),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
