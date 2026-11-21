"""Validates that every gold JSON file in the hackathon dataset parses
cleanly through the runtime Pydantic model generated from the matching
DocClassSpec YAML -- the end-to-end check that the declarative spec actually
matches reality, not just that it loads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab.paths import data_root
from o2jcore.spec.loader import load_all_classes
from o2jcore.spec.pydantic_build import build_model

REPO_ROOT = Path(__file__).resolve().parents[1]

# maps DocClassSpec.id -> gold JSON filename stem (see configs/classes/*.yaml
# gold_stem -- potwierdzenie_przelewu's PDF pairs with a gold file literally
# named przelew.json, a real mismatch in the training data).
_CLASS_IDS = ("odwolanie", "pelnomocnictwo", "potwierdzenie_przelewu")


@pytest.fixture(scope="module")
def specs():
    return load_all_classes(REPO_ROOT / "configs" / "classes")


@pytest.fixture(scope="module")
def models(specs):
    return {cid: build_model(specs[cid]) for cid in _CLASS_IDS}


def test_all_gold_files_validate(specs, models):
    dane_dir = data_root() / "dane"
    assert dane_dir.is_dir(), f"expected gold data dir at {dane_dir}"

    checked = 0
    failures: list[tuple[str, str]] = []

    for example_dir in sorted(dane_dir.glob("przyklad_*")):
        if not example_dir.is_dir():
            continue
        for cid in _CLASS_IDS:
            gold_stem = specs[cid].gold_stem
            gold_path = example_dir / f"{gold_stem}.json"
            if not gold_path.exists():
                continue
            checked += 1
            raw = json.loads(gold_path.read_text(encoding="utf-8"))
            try:
                models[cid].model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - we want every failure, not just the first
                failures.append((str(gold_path), repr(exc)))

    assert checked == 180, f"expected to check exactly 180 gold files, checked {checked}"

    if failures:
        detail = "\n".join(f"{path}:\n{err}" for path, err in failures)
        pytest.fail(f"{len(failures)} gold file(s) failed validation:\n{detail}")
