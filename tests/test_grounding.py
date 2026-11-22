"""Tests for post-extraction grounding, derived fields and class routing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from lab import paths
from lab.cache import read_cached
from lab.llm.classify import classify_by_rules
from lab.llm.grounding import enforce_derived, ground_object
from lab.llm.text_prep import prepare_ocr_text
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = paths.data_root() / "dane"
SPECS = load_all_classes(REPO_ROOT / "configs" / "classes")


def _text(set_id: str, cid: str) -> str:
    pdf = GOLD_DIR / set_id / f"{SPECS[cid].pdf_stem}.pdf"
    cached = read_cached(paths.work_root() / "cache", pdf, "pdfplumber")
    assert cached is not None
    return prepare_ocr_text(cached["pages"])


def test_grounding_nulls_ungrounded_free_text_but_not_dates():
    spec = SPECS["odwolanie"]
    obj = json.loads((GOLD_DIR / "przyklad_01" / "odwolanie.json").read_text(encoding="utf-8"))
    obj = copy.deepcopy(obj)
    original_date = obj["OdwolanieKIO"]["data"]
    obj["OdwolanieKIO"]["miejscowosc"] = "Zmyślone Miasto Kujawskie"

    nulled = ground_object(obj, spec, _text("przyklad_01", "odwolanie"))

    assert nulled >= 1
    assert obj["OdwolanieKIO"]["miejscowosc"] is None
    assert obj["OdwolanieKIO"]["data"] == original_date


def test_enforce_derived_repairs_czynnosc_opis_from_enum_map():
    spec = SPECS["odwolanie"]
    obj = json.loads((GOLD_DIR / "przyklad_01" / "odwolanie.json").read_text(encoding="utf-8"))
    enum = yaml.safe_load((REPO_ROOT / "configs/enums/czynnosc_powod.yaml").read_text(encoding="utf-8"))
    key = int(obj["OdwolanieKIO"]["czynnosc_powod_id"])
    obj["OdwolanieKIO"]["czynnosc_opis"] = "zły opis"

    changed = enforce_derived(obj, spec)

    assert changed == 1
    assert obj["OdwolanieKIO"]["czynnosc_opis"] == enum[key]


def test_classify_rules_routes_all_180_pdfs_from_text_alone():
    """Routing must hold without the filename, which the graded set randomises."""
    for set_dir in sorted(GOLD_DIR.glob("przyklad_*")):
        for cid in SPECS:
            assert classify_by_rules(_text(set_dir.name, cid)) == cid


def test_classify_rules_returns_none_for_empty_text():
    assert classify_by_rules("") is None
