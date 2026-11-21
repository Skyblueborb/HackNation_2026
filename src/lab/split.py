"""Stratified, seeded, reproducible dev/holdout split over the training sets.

The 60 training sets live at ``<data_root>/dane/przyklad_01`` ..
``przyklad_60``, each holding three gold JSON files (``odwolanie.json``,
``pelnomocnictwo.json``, ``przelew.json``) plus their source PDFs. We split
**by set**, never by individual file, since the three documents in a set must
travel together.

Stratification keys (computed by scanning the raw gold JSON, no pydantic
machinery required):

- ``block``: "A" for sets 1-39, "B" for sets 40-60. This is the hard
  constraint: block B sets are long, structurally richer documents, so the
  dev/holdout proportion is enforced *per block*, not just overall.
- ``czynnosc_powod_id``: ``OdwolanieKIO.czynnosc_powod_id`` (int, 1-11).
- ``n_zamawiajacy_multi``: ``len(Zamawiajacy) > 1`` in ``odwolanie.json``.
- ``n_mocodawca_multi``: ``len(mocodawca) > 1`` in ``pelnomocnictwo.json``.
- ``n_pelnomocnicy_multi``: ``len(pelnomocnicy) > 1`` in
  ``pelnomocnictwo.json``.
- ``header_null``: ``OdwolanieKIO.data is None`` in ``odwolanie.json``.

Algorithm
---------

1. Scan all 60 sets and compute the feature vector above for each.
2. The handful of sets with ``n_zamawiajacy_multi`` (multiple Zamawiajacy) are
   special-cased: they're rare enough (3 out of 60 as measured on the actual
   dataset) that leaving them to the general greedy algorithm risks an
   unlucky placement. They're assigned explicitly, proportionally, with the
   seeded RNG choosing *which* ones land in holdout (so different seeds can
   still produce different splits).
3. Every other set is assigned by a greedy rarity-first pass: sets are
   ordered so that sets whose (block, czynnosc_powod_id, n_mocodawca_multi,
   n_pelnomocnicy_multi, header_null) combination is least common (globally
   rare) get placed first -- this avoids rare combinations accidentally
   clustering into one split purely by chance. Within a rarity tier, order is
   randomized with the seeded RNG. Each set, in that order, is assigned to
   whichever of {dev, holdout} currently has the larger deficit relative to
   its *per-block* target (computed via the largest-remainder method so the
   per-block dev/holdout counts are exact integers summing correctly),
   breaking exact ties with the seeded RNG.
4. The whole procedure is a deterministic function of (data, n_holdout,
   seed): no unseeded randomness is used anywhere.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

SET_NAME_PREFIX = "przyklad_"


def _set_number(name: str) -> int:
    return int(name[len(SET_NAME_PREFIX) :])


def _block_for(set_number: int) -> str:
    return "A" if set_number <= 39 else "B"


def _scan_sets(data_root: Path) -> dict[str, dict[str, Any]]:
    """Scan every training set under ``<data_root>/dane`` and compute features.

    Returns a mapping of set name (e.g. "przyklad_01") to its feature dict.
    """
    sets_dir = data_root / "dane"
    set_dirs = sorted(
        (p for p in sets_dir.glob(f"{SET_NAME_PREFIX}*") if p.is_dir()),
        key=lambda p: _set_number(p.name),
    )
    if not set_dirs:
        raise RuntimeError(f"no training sets found under {sets_dir}")

    features: dict[str, dict[str, Any]] = {}
    for set_dir in set_dirs:
        name = set_dir.name
        odwolanie = json.loads((set_dir / "odwolanie.json").read_text(encoding="utf-8"))
        pelnomocnictwo = json.loads(
            (set_dir / "pelnomocnictwo.json").read_text(encoding="utf-8")
        )

        kio = odwolanie["OdwolanieKIO"]
        zamawiajacy = odwolanie.get("Zamawiajacy") or []
        mocodawca = pelnomocnictwo.get("mocodawca") or []
        pelnomocnicy = pelnomocnictwo.get("pelnomocnicy") or []

        features[name] = {
            "block": _block_for(_set_number(name)),
            "czynnosc_powod_id": kio["czynnosc_powod_id"],
            "n_zamawiajacy_multi": len(zamawiajacy) > 1,
            "n_mocodawca_multi": len(mocodawca) > 1,
            "n_pelnomocnicy_multi": len(pelnomocnicy) > 1,
            "header_null": kio["data"] is None,
        }
    return features


def _largest_remainder_targets(
    block_counts: dict[str, int], n_holdout: int, total: int
) -> dict[str, int]:
    """Per-block holdout targets that are exact integers summing to n_holdout.

    Uses the largest-remainder (Hamilton) apportionment method: each block
    gets floor(count * n_holdout / total), then the remaining seats go to the
    blocks with the largest fractional remainder, ties broken by block name
    for determinism.
    """
    exact = {b: count * n_holdout / total for b, count in block_counts.items()}
    floor_vals = {b: int(v) for b, v in exact.items()}
    remainder = n_holdout - sum(floor_vals.values())
    ordered = sorted(
        block_counts.keys(), key=lambda b: (-(exact[b] - floor_vals[b]), b)
    )
    for b in ordered[:remainder]:
        floor_vals[b] += 1
    return floor_vals


def build_split(data_root: Path, n_holdout: int, seed: int) -> dict:
    """Build a stratified, seeded, reproducible dev/holdout split by set.

    Returns a dict with keys: seed, n_dev, n_holdout, dev, holdout,
    contingency. See module docstring for the stratification keys and
    algorithm.
    """
    features = _scan_sets(Path(data_root))
    all_names = sorted(features.keys(), key=_set_number)
    total = len(all_names)
    n_dev = total - n_holdout

    block_counts: dict[str, int] = Counter(features[n]["block"] for n in all_names)

    # Per-block holdout targets over *all* sets, computed once up front so
    # the hard block constraint is exact (not approximate).
    block_holdout_target = _largest_remainder_targets(block_counts, n_holdout, total)
    block_dev_target = {
        b: block_counts[b] - block_holdout_target[b] for b in block_counts
    }

    rng = random.Random(seed)

    # --- Step 1: special-case the n_zamawiajacy_multi sets. ---
    # These sets (multiple Zamawiajacy in one odwolanie) are rare -- 3 out of
    # 60 on the measured dataset -- so we assign them deliberately rather
    # than trusting the general greedy pass not to accidentally cluster all
    # of them into one split. We keep the split proportional to the overall
    # holdout fraction (round(), with a floor of 0) rather than hardcoding
    # "2 dev / 1 holdout", so the function still behaves sensibly if called
    # with a different n_holdout; on the measured dataset (3 sets, 20/60
    # holdout fraction) this naturally yields exactly 1 holdout / 2 dev,
    # which matches the explicit requirement.
    zam_multi_names = sorted(
        (n for n in all_names if features[n]["n_zamawiajacy_multi"]),
        key=_set_number,
    )
    holdout_fraction = n_holdout / total
    zam_holdout_n = round(len(zam_multi_names) * holdout_fraction)
    zam_holdout_n = max(0, min(len(zam_multi_names), zam_holdout_n))

    shuffled_zam = list(zam_multi_names)
    rng.shuffle(shuffled_zam)
    zam_holdout = set(shuffled_zam[:zam_holdout_n])
    zam_dev = set(shuffled_zam[zam_holdout_n:])

    assigned: dict[str, str] = {}
    for n in zam_holdout:
        assigned[n] = "holdout"
    for n in zam_dev:
        assigned[n] = "dev"

    # Reduce the remaining per-block targets by what the special case already
    # consumed.
    remaining_holdout_target = dict(block_holdout_target)
    remaining_dev_target = dict(block_dev_target)
    for n in zam_multi_names:
        b = features[n]["block"]
        if assigned[n] == "holdout":
            remaining_holdout_target[b] -= 1
        else:
            remaining_dev_target[b] -= 1

    # Also compute (soft) per-czynnosc_powod_id holdout/dev targets over all
    # 60 sets, via the same largest-remainder method as the block targets.
    # `block` is the hard constraint (enforced as per-block capacity below);
    # `czynnosc_powod_id` is a secondary objective used to break ties between
    # dev/holdout whenever the block constraint leaves both sides available,
    # so that each id's holdout count tracks its proportional share instead
    # of drifting arbitrarily.
    id_counts: dict[int, int] = Counter(features[n]["czynnosc_powod_id"] for n in all_names)
    id_holdout_target = _largest_remainder_targets(id_counts, n_holdout, total)
    id_dev_target = {cid: id_counts[cid] - id_holdout_target[cid] for cid in id_counts}
    remaining_id_holdout_target = dict(id_holdout_target)
    remaining_id_dev_target = dict(id_dev_target)
    for n in zam_multi_names:
        cid = features[n]["czynnosc_powod_id"]
        if assigned[n] == "holdout":
            remaining_id_holdout_target[cid] -= 1
        else:
            remaining_id_dev_target[cid] -= 1

    # --- Step 2: greedy rarity-first pass over everything else. ---
    remaining_names = [n for n in all_names if n not in assigned]

    def combo_key(n: str) -> tuple:
        f = features[n]
        return (
            f["block"],
            f["czynnosc_powod_id"],
            f["n_mocodawca_multi"],
            f["n_pelnomocnicy_multi"],
            f["header_null"],
        )

    combo_freq: Counter[tuple] = Counter(combo_key(n) for n in remaining_names)

    # Randomize order (seeded) first, then stable-sort by rarity ascending --
    # this makes the within-rarity-tier order depend on the seed while
    # keeping the rarity ordering itself deterministic.
    order = list(remaining_names)
    rng.shuffle(order)
    order.sort(key=lambda n: combo_freq[combo_key(n)])

    dev_count: dict[str, int] = {b: 0 for b in block_counts}
    holdout_count: dict[str, int] = {b: 0 for b in block_counts}
    id_dev_count: dict[int, int] = {cid: 0 for cid in id_counts}
    id_holdout_count: dict[int, int] = {cid: 0 for cid in id_counts}

    for n in order:
        b = features[n]["block"]
        cid = features[n]["czynnosc_powod_id"]

        # Hard constraint: remaining capacity per block/split. Once one side
        # is full for this block, the other is forced.
        dev_capacity = remaining_dev_target[b] - dev_count[b]
        holdout_capacity = remaining_holdout_target[b] - holdout_count[b]
        allowed = []
        if dev_capacity > 0:
            allowed.append("dev")
        if holdout_capacity > 0:
            allowed.append("holdout")

        if len(allowed) == 1:
            choice = allowed[0]
        else:
            # Both sides still have room for this block: use the softer
            # czynnosc_powod_id deficit as a tiebreak so id proportions stay
            # close to their target, then fall back to the block deficit,
            # then to the seeded RNG for an exact tie.
            id_dev_deficit = remaining_id_dev_target[cid] - id_dev_count[cid]
            id_holdout_deficit = remaining_id_holdout_target[cid] - id_holdout_count[cid]
            if id_dev_deficit > id_holdout_deficit:
                choice = "dev"
            elif id_holdout_deficit > id_dev_deficit:
                choice = "holdout"
            elif dev_capacity > holdout_capacity:
                choice = "dev"
            elif holdout_capacity > dev_capacity:
                choice = "holdout"
            else:
                choice = rng.choice(["dev", "holdout"])

        assigned[n] = choice
        if choice == "dev":
            dev_count[b] += 1
            id_dev_count[cid] += 1
        else:
            holdout_count[b] += 1
            id_holdout_count[cid] += 1

    dev = sorted((n for n, v in assigned.items() if v == "dev"), key=_set_number)
    holdout = sorted(
        (n for n, v in assigned.items() if v == "holdout"), key=_set_number
    )

    assert len(dev) + len(holdout) == total
    assert set(dev) & set(holdout) == set()
    assert len(dev) == n_dev
    assert len(holdout) == n_holdout

    contingency = _build_contingency(features, assigned)

    return {
        "seed": seed,
        "n_dev": n_dev,
        "n_holdout": n_holdout,
        "dev": dev,
        "holdout": holdout,
        "contingency": contingency,
    }


def _build_contingency(
    features: dict[str, dict[str, Any]], assigned: dict[str, str]
) -> dict[str, Any]:
    def counts_by(key: str) -> dict[str, dict[str, int]]:
        table: dict[Any, dict[str, int]] = {}
        for name, split in assigned.items():
            value = features[name][key]
            table.setdefault(value, {"dev": 0, "holdout": 0})
            table[value][split] += 1
        # JSON object keys must be strings.
        return {str(k): v for k, v in sorted(table.items(), key=lambda kv: str(kv[0]))}

    def bool_counts(key: str) -> dict[str, int]:
        table = {"dev": 0, "holdout": 0}
        for name, split in assigned.items():
            if features[name][key]:
                table[split] += 1
        return table

    return {
        "block": counts_by("block"),
        "czynnosc_powod_id": counts_by("czynnosc_powod_id"),
        "n_zamawiajacy_multi": bool_counts("n_zamawiajacy_multi"),
        "n_mocodawca_multi": bool_counts("n_mocodawca_multi"),
        "n_pelnomocnicy_multi": bool_counts("n_pelnomocnicy_multi"),
        "header_null": bool_counts("header_null"),
    }


def write_split(result: dict, work_root: Path) -> Path:
    """Write the split result to ``<work_root>/splits.json``, returning its path."""
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    out_path = work_root / "splits.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return out_path


def format_summary(result: dict) -> str:
    """Render a short human-readable summary table for stdout."""
    lines: list[str] = []
    lines.append(
        f"seed={result['seed']}  n_dev={result['n_dev']}  n_holdout={result['n_holdout']}"
    )
    lines.append("")
    contingency = result["contingency"]
    for key, table in contingency.items():
        lines.append(f"-- {key} --")
        if "dev" in table and "holdout" in table and set(table.keys()) == {"dev", "holdout"}:
            lines.append(f"  dev={table['dev']}  holdout={table['holdout']}")
        else:
            for value, counts in table.items():
                lines.append(f"  {value}: dev={counts['dev']}  holdout={counts['holdout']}")
        lines.append("")
    return "\n".join(lines)
