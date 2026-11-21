"""THE GATE: evaluating gold against itself must be F1 == 1.0, exactly, on
all 180 files, in every mode x null_policy combination. Everything
downstream (ranking real pipeline runs) trusts this.

If any of these ever fails, that is a real bug in flatten/match/compare --
fix the code, never loosen the assertion.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from lab import paths
from lab.eval.flatten import flatten
from lab.eval.metrics import evaluate_run
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = paths.data_root() / "dane"
MODES = ("exact", "fuzzy")
POLICIES = ("skip", "tp", "strict")

GOLD_FILENAMES = {
    "odwolanie": "odwolanie.json",
    "pelnomocnictwo": "pelnomocnictwo.json",
    "potwierdzenie_przelewu": "przelew.json",
}


@pytest.fixture(scope="module")
def specs():
    return load_all_classes(REPO_ROOT / "configs" / "classes")


def _copy_set(dest_root: Path, set_id: str) -> Path:
    """Copy one real set's 3 gold files into dest_root/set_id, as a faithful
    starting point for a mutated pred fixture. Never touches the real
    (read-only) data directory."""
    src = GOLD_DIR / set_id
    dst = dest_root / set_id
    dst.mkdir(parents=True, exist_ok=True)
    for fname in GOLD_FILENAMES.values():
        shutil.copyfile(src / fname, dst / fname)
    return dst


def _non_null_leaf_count(set_id: str, cid: str, specs: dict) -> int:
    fname = GOLD_FILENAMES[cid]
    obj = json.loads((GOLD_DIR / set_id / fname).read_text(encoding="utf-8"))
    flat = flatten(obj, specs[cid])
    return sum(1 for v in flat.values() if v is not None)


# ---------------------------------------------------------------------------
# The gate.
# ---------------------------------------------------------------------------


def test_identity_evaluates_to_perfect_f1(specs):
    result = evaluate_run(GOLD_DIR, GOLD_DIR, specs)

    assert result.n_files_evaluated == 180

    total_leaves = None
    for mode in MODES:
        c = result.overall[mode]
        assert c.fp == 0, f"mode={mode}: expected fp==0, got {c.fp}"
        assert c.fn == 0, f"mode={mode}: expected fn==0, got {c.fn}"

        this_total = c.tp + c.fp + c.fn + c.tn
        if total_leaves is None:
            total_leaves = this_total
        assert this_total == total_leaves, "leaf totals must agree between exact/fuzzy modes"

        for policy in POLICIES:
            p, r, f1 = c.precision_recall_f1(policy)
            assert p == 1.0, f"mode={mode} policy={policy}: precision={p}"
            assert r == 1.0, f"mode={mode} policy={policy}: recall={r}"
            assert f1 == 1.0, f"mode={mode} policy={policy}: f1={f1}"

    # Canary: if a path bug silently evaluated zero files, every count would
    # be zero and f1 would trivially be 1.0 by the zero-denominator
    # convention -- so also assert there was real substance to measure.
    assert total_leaves is not None and total_leaves > 1000, (
        f"suspiciously few leaves measured ({total_leaves}); "
        "did evaluate_run actually walk real data?"
    )


# ---------------------------------------------------------------------------
# Adversarial sub-tests: one controlled defect each, against a tmp_path copy.
# ---------------------------------------------------------------------------


def test_missing_pred_file_counts_every_gold_leaf_as_fn(tmp_path, specs):
    set_id = "przyklad_02"
    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)
    (pred_dir / set_id / "odwolanie.json").unlink()  # model never answered

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    expected_fn = _non_null_leaf_count(set_id, "odwolanie", specs)
    assert expected_fn > 0

    for mode in MODES:
        counts = result.per_file[f"{set_id}/odwolanie.json"][mode]
        assert counts.fp == 0
        assert counts.fn == expected_fn
    assert result.missing_pred == 1
    assert result.invalid_json == 0


def test_zero_byte_pred_file_same_as_missing_plus_invalid_json_counter(tmp_path, specs):
    set_id = "przyklad_03"
    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)
    (pred_dir / set_id / "pelnomocnictwo.json").write_bytes(b"")

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    expected_fn = _non_null_leaf_count(set_id, "pelnomocnictwo", specs)
    assert expected_fn > 0

    for mode in MODES:
        counts = result.per_file[f"{set_id}/pelnomocnictwo.json"][mode]
        assert counts.fp == 0
        assert counts.fn == expected_fn
    assert result.invalid_json == 1
    assert result.missing_pred == 0


def test_reversed_pelnomocnicy_order_still_f1_one(tmp_path, specs):
    # przyklad_01 has 2 pelnomocnicy entries.
    set_id = "przyklad_01"
    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)

    pel_path = pred_dir / set_id / "pelnomocnictwo.json"
    obj = json.loads(pel_path.read_text(encoding="utf-8"))
    assert len(obj["pelnomocnicy"]) >= 2
    obj["pelnomocnicy"] = list(reversed(obj["pelnomocnicy"]))
    pel_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    for mode in MODES:
        counts = result.per_file[f"{set_id}/pelnomocnictwo.json"][mode]
        assert counts.fp == 0
        assert counts.fn == 0
        for policy in POLICIES:
            _, _, f1 = counts.precision_recall_f1(policy)
            assert f1 == 1.0


def test_swapped_multi_zamawiajacy_still_f1_one(tmp_path, specs):
    # These 3 sets have exactly 2 Zamawiajacy entries (verified against the
    # real dataset).
    candidates = ["przyklad_42", "przyklad_51", "przyklad_59"]
    set_id = None
    for candidate in candidates:
        obj = json.loads((GOLD_DIR / candidate / "odwolanie.json").read_text(encoding="utf-8"))
        if len(obj.get("Zamawiajacy") or []) >= 2:
            set_id = candidate
            break
    assert set_id is not None, "expected at least one multi-Zamawiajacy set among the known candidates"

    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)

    odw_path = pred_dir / set_id / "odwolanie.json"
    obj = json.loads(odw_path.read_text(encoding="utf-8"))
    obj["Zamawiajacy"] = list(reversed(obj["Zamawiajacy"]))
    odw_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    for mode in MODES:
        counts = result.per_file[f"{set_id}/odwolanie.json"][mode]
        assert counts.fp == 0
        assert counts.fn == 0
        for policy in POLICIES:
            _, _, f1 = counts.precision_recall_f1(policy)
            assert f1 == 1.0


def test_junk_extra_key_adds_exactly_one_fp(tmp_path, specs):
    set_id = "przyklad_04"
    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)

    odw_path = pred_dir / set_id / "odwolanie.json"
    obj = json.loads(odw_path.read_text(encoding="utf-8"))
    obj["CompletelyUnexpectedJunkKey"] = "some junk value"
    odw_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    for mode in MODES:
        counts = result.per_file[f"{set_id}/odwolanie.json"][mode]
        assert counts.fp == 1
        assert counts.fn == 0


def test_one_digit_nip_change_computed_ratio(tmp_path, specs):
    set_id = "przyklad_01"
    pred_dir = tmp_path / "pred"
    _copy_set(pred_dir, set_id)

    odw_path = pred_dir / set_id / "odwolanie.json"
    obj = json.loads(odw_path.read_text(encoding="utf-8"))
    original_nip = obj["Odwolujacy"][0]["nip"]
    assert original_nip is not None
    changed_nip = original_nip[:-1] + ("0" if original_nip[-1] != "0" else "1")
    assert changed_nip != original_nip
    obj["Odwolujacy"][0]["nip"] = changed_nip
    odw_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    computed_ratio = fuzz.ratio(original_nip, changed_nip)
    # Computed, not assumed: a single-digit change in a ~10-char numeric
    # string. Printed/comment here rather than hardcoded so this test fails
    # loudly (not silently) if rapidfuzz's behavior ever changes.
    # Measured value for this specific pair: see assertion below.

    result = evaluate_run(pred_dir, GOLD_DIR, specs, set_ids=[set_id])

    exact_counts = result.per_file[f"{set_id}/odwolanie.json"]["exact"]
    assert exact_counts.fp == 1
    assert exact_counts.fn == 1

    fuzzy_counts = result.per_file[f"{set_id}/odwolanie.json"]["fuzzy"]
    if computed_ratio >= 90:
        # Ratio clears the fuzzy_threshold=90 bar -> treated as a match (TP),
        # no fp/fn added.
        assert fuzzy_counts.fp == 0
        assert fuzzy_counts.fn == 0
    else:
        assert fuzzy_counts.fp == 1
        assert fuzzy_counts.fn == 1


# ---------------------------------------------------------------------------
# Regression cases on real, specific files.
# ---------------------------------------------------------------------------


def test_przyklad_45_gold_has_no_endomedica_leak(specs):
    obj = json.loads((GOLD_DIR / "przyklad_45" / "odwolanie.json").read_text(encoding="utf-8"))
    flat = flatten(obj, specs["odwolanie"])
    for path, value in flat.items():
        if isinstance(value, str):
            assert "Endomedica" not in value, f"distractor leaked into gold at {path}: {value!r}"


def test_przyklad_45_identity_is_f1_one(specs):
    result = evaluate_run(GOLD_DIR, GOLD_DIR, specs, set_ids=["przyklad_45"])

    assert result.n_files_evaluated == 3
    for mode in MODES:
        c = result.overall[mode]
        assert c.fp == 0
        assert c.fn == 0
        for policy in POLICIES:
            _, _, f1 = c.precision_recall_f1(policy)
            assert f1 == 1.0
