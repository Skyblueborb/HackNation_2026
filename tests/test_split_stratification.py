"""Tests for the stratified dev/holdout split (lab split / lab.split)."""

from __future__ import annotations

import json

from lab import paths
from lab.split import _scan_sets, build_split

DATA_ROOT = paths.data_root()
N_HOLDOUT = 20
SEED = 42


def test_dev_holdout_partition_is_exact():
    result = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    dev = set(result["dev"])
    holdout = set(result["holdout"])

    assert dev & holdout == set()
    assert len(dev) == result["n_dev"]
    assert len(holdout) == result["n_holdout"]

    features = _scan_sets(DATA_ROOT)
    assert dev | holdout == set(features.keys())


def test_block_counts_match_computed_targets_exactly():
    result = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    features = _scan_sets(DATA_ROOT)

    # Measured on the real dataset: 39 block-A sets, 21 block-B sets.
    block_counts = {"A": 0, "B": 0}
    for f in features.values():
        block_counts[f["block"]] += 1
    assert block_counts == {"A": 39, "B": 21}

    # 20/60 holdout fraction is exactly 1/3, so the largest-remainder
    # apportionment is exact (no rounding ambiguity): A -> 13 holdout / 26
    # dev, B -> 7 holdout / 14 dev.
    block_table = result["contingency"]["block"]
    assert block_table["A"] == {"dev": 26, "holdout": 13}
    assert block_table["B"] == {"dev": 14, "holdout": 7}

    # Cross-check against the actual dev/holdout lists, not just the
    # reported contingency table.
    dev_set = set(result["dev"])
    holdout_set = set(result["holdout"])
    for block, expected in (("A", block_table["A"]), ("B", block_table["B"])):
        names_in_block = [n for n, f in features.items() if f["block"] == block]
        dev_in_block = sum(1 for n in names_in_block if n in dev_set)
        holdout_in_block = sum(1 for n in names_in_block if n in holdout_set)
        assert dev_in_block == expected["dev"]
        assert holdout_in_block == expected["holdout"]


def test_zamawiajacy_multi_sets_split_two_dev_one_holdout():
    result = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    features = _scan_sets(DATA_ROOT)

    zam_multi_names = [n for n, f in features.items() if f["n_zamawiajacy_multi"]]
    # Measured on the real dataset: exactly 3 such sets.
    assert len(zam_multi_names) == 3

    dev_set = set(result["dev"])
    holdout_set = set(result["holdout"])
    dev_n = sum(1 for n in zam_multi_names if n in dev_set)
    holdout_n = sum(1 for n in zam_multi_names if n in holdout_set)
    assert (dev_n, holdout_n) == (2, 1)

    assert result["contingency"]["n_zamawiajacy_multi"] == {"dev": 2, "holdout": 1}


def test_czynnosc_powod_id_holdout_counts_within_tolerance():
    # With 20/60 holdout and 11 possible czynnosc_powod_id values, exact
    # proportional coverage isn't guaranteed for every id (e.g. an id with
    # only 4 occurrences can't be split into a holdout count that is exactly
    # 4 * 20/60 = 1.33...). We assert each id's holdout count is within +-1
    # of the ideal proportional value instead of requiring exact equality.
    result = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    features = _scan_sets(DATA_ROOT)

    total_by_id: dict[int, int] = {}
    for f in features.values():
        cid = f["czynnosc_powod_id"]
        total_by_id[cid] = total_by_id.get(cid, 0) + 1

    holdout_fraction = N_HOLDOUT / 60
    holdout_table = result["contingency"]["czynnosc_powod_id"]
    for cid, total in total_by_id.items():
        ideal = holdout_fraction * total
        actual = holdout_table[str(cid)]["holdout"]
        assert abs(actual - ideal) <= 1 + 1e-9, (
            f"czynnosc_powod_id={cid}: holdout count {actual} too far from "
            f"ideal {ideal} (total {total})"
        )


def test_build_split_is_deterministic_given_same_seed():
    result1 = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    result2 = build_split(DATA_ROOT, N_HOLDOUT, seed=SEED)
    assert result1 == result2
    # Also check JSON-serialized form is byte-identical, matching the CLI's
    # "running lab split twice produces byte-identical splits.json" guarantee.
    assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)


def _assert_valid_split(result: dict) -> None:
    dev = set(result["dev"])
    holdout = set(result["holdout"])
    assert dev & holdout == set()
    assert len(dev) == result["n_dev"]
    assert len(holdout) == result["n_holdout"]

    block_table = result["contingency"]["block"]
    assert block_table["A"] == {"dev": 26, "holdout": 13}
    assert block_table["B"] == {"dev": 14, "holdout": 7}

    assert result["contingency"]["n_zamawiajacy_multi"] == {"dev": 2, "holdout": 1}


def test_different_seed_changes_outcome_but_stays_valid():
    result_42 = build_split(DATA_ROOT, N_HOLDOUT, seed=42)
    result_43 = build_split(DATA_ROOT, N_HOLDOUT, seed=43)

    _assert_valid_split(result_42)
    _assert_valid_split(result_43)

    assert result_42["dev"] != result_43["dev"] or result_42["holdout"] != result_43["holdout"]
