"""Tests for lab.eval.metrics: Counts.add and precision_recall_f1 edge cases."""

from __future__ import annotations

import json

import pytest

from lab.eval.compare import Verdict
from lab.eval.metrics import Counts, evaluate_run
from o2jcore.spec.models import DocClassSpec, FieldSpec


def test_counts_add_fpfn_increments_both_fp_and_fn():
    c = Counts()
    c.add(Verdict.FPFN)
    assert c.fp == 1
    assert c.fn == 1
    assert c.tp == 0
    assert c.tn == 0


def test_counts_add_each_verdict_increments_its_own_counter():
    c = Counts()
    c.add(Verdict.TP)
    c.add(Verdict.FP)
    c.add(Verdict.FN)
    c.add(Verdict.TN)
    assert (c.tp, c.fp, c.fn, c.tn) == (1, 1, 1, 1)


# --- precision_recall_f1 edge cases -----------------------------------------
# Each case: (tp, fp, fn, tn, null_policy, expected_precision, expected_recall, expected_f1)
EDGE_CASES = [
    # Everything zero: nothing predicted, nothing in gold, nothing null either.
    # tp+fp == 0 and fn == 0 -> precision vacuously 1.0.
    # tp+fn == 0 and fp == 0 -> recall vacuously 1.0. -> F1 = 1.0.
    (0, 0, 0, 0, "skip", 1.0, 1.0, 1.0),
    # Nothing predicted (tp+fp==0), but gold had something we missed (fn>0)
    # -> precision convention says 0.0 (we have fn>0 so "missed something").
    # recall: tp+fn>0 so normal division: 0/fn = 0.0. F1 = 0.0.
    (0, 0, 3, 0, "skip", 0.0, 0.0, 0.0),
    # Predicted something spurious (fp>0), nothing in gold (tp+fn==0, fp>0)
    # -> recall convention: tp+fn==0 but fp>0 -> 0.0 (recall undefined but we
    # did produce something incorrectly, so not vacuously perfect).
    # precision: tp+fp>0 -> 0/fp = 0.0. F1 = 0.0.
    (0, 2, 0, 0, "skip", 0.0, 0.0, 0.0),
    # Perfect: everything correct, nothing wrong.
    (5, 0, 0, 0, "skip", 1.0, 1.0, 1.0),
    # Normal mixed case (no edge denominators).
    (3, 1, 1, 0, "skip", 0.75, 0.75, 0.75),
    # 'tp' policy folds tn in as an extra true positive source.
    # all-null-vs-null (tn only) -> P = tn/(tn) = 1.0 (fn==0), R likewise.
    (0, 0, 0, 7, "tp", 1.0, 1.0, 1.0),
    # 'tp' policy, tn present alongside a real fp/fn.
    (0, 1, 1, 4, "tp", 4 / 5, 4 / 5, 4 / 5),
    # 'strict' is a literal alias of 'skip' at this level.
    (3, 1, 1, 10, "strict", 0.75, 0.75, 0.75),
    (0, 0, 0, 0, "strict", 1.0, 1.0, 1.0),
]


@pytest.mark.parametrize("tp,fp,fn,tn,policy,exp_p,exp_r,exp_f1", EDGE_CASES)
def test_precision_recall_f1_edge_cases(tp, fp, fn, tn, policy, exp_p, exp_r, exp_f1):
    c = Counts(tp=tp, fp=fp, fn=fn, tn=tn)
    p, r, f1 = c.precision_recall_f1(policy)
    assert p == pytest.approx(exp_p)
    assert r == pytest.approx(exp_r)
    assert f1 == pytest.approx(exp_f1)


def test_strict_is_exact_alias_of_skip_at_counts_level():
    # Field-requiredness escalation (where 'strict' would diverge from
    # 'skip') is explicitly out of scope for A4 -- see Counts docstring.
    for tp, fp, fn, tn in [(0, 0, 0, 0), (3, 1, 1, 10), (0, 5, 0, 2), (1, 0, 0, 0)]:
        c = Counts(tp=tp, fp=fp, fn=fn, tn=tn)
        assert c.precision_recall_f1("strict") == c.precision_recall_f1("skip")


def test_unknown_null_policy_raises():
    c = Counts(tp=1)
    with pytest.raises(ValueError):
        c.precision_recall_f1("bogus")


# --- evaluate_run: extras and json validity ----------------------------------


def _tiny_specs() -> dict:
    spec = DocClassSpec(
        id="tiny",
        title="Tiny",
        pdf_stem="tiny",
        gold_stem="tiny",
        fields=[FieldSpec(path="a", kind="string", nullable=True, normalizer="text")],
    )
    return {"tiny": spec}


def _gold_pred_dirs(tmp_path, *, pred_obj=None):
    gold = tmp_path / "gold"
    pred = tmp_path / "pred"
    for root in (gold, pred):
        (root / "przyklad_01").mkdir(parents=True)
    (gold / "przyklad_01" / "tiny.json").write_text(json.dumps({"a": "x"}), encoding="utf-8")
    if pred_obj is not None:
        (pred / "przyklad_01" / "tiny.json").write_text(json.dumps(pred_obj), encoding="utf-8")
    return gold, pred


def test_gold_side_extra_keys_are_not_false_positives(tmp_path):
    # The gold document itself carries an unexpected key. An identical pred
    # must score perfectly -- gold quirks are not model mistakes.
    gold, pred = _gold_pred_dirs(tmp_path, pred_obj={"a": "x", "gold_only": "junk"})
    (gold / "przyklad_01" / "tiny.json").write_text(
        json.dumps({"a": "x", "gold_only": "junk"}), encoding="utf-8"
    )

    result = evaluate_run(pred, gold, _tiny_specs(), set_ids=["przyklad_01"])

    for mode in ("exact", "fuzzy"):
        c = result.overall[mode]
        assert (c.tp, c.fp, c.fn) == (1, 0, 0)


def test_only_pred_only_extra_keys_are_false_positives(tmp_path):
    gold, pred = _gold_pred_dirs(tmp_path, pred_obj={"a": "x", "pred_only": "junk"})

    result = evaluate_run(pred, gold, _tiny_specs(), set_ids=["przyklad_01"])

    for mode in ("exact", "fuzzy"):
        c = result.overall[mode]
        assert c.fp == 1
        assert c.fn == 0


def test_json_invalid_or_missing_counts_each_doc_once(tmp_path):
    gold = tmp_path / "gold"
    pred = tmp_path / "pred"
    for set_id in ("przyklad_01", "przyklad_02", "przyklad_03"):
        (gold / set_id).mkdir(parents=True)
        (pred / set_id).mkdir(parents=True)
        (gold / set_id / "tiny.json").write_text(json.dumps({"a": "x"}), encoding="utf-8")
    (pred / "przyklad_01" / "tiny.json").write_text(json.dumps({"a": "x"}), encoding="utf-8")
    (pred / "przyklad_03" / "tiny.json").write_bytes(b"")

    result = evaluate_run(
        pred, gold, _tiny_specs(), set_ids=["przyklad_01", "przyklad_02", "przyklad_03"]
    )

    assert result.n_files_evaluated == 3
    assert result.missing_pred == 1
    assert result.invalid_json == 1
    assert result.json_invalid_or_missing == 2
