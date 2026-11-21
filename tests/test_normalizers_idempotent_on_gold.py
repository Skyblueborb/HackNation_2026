"""The important test: normalizers must be idempotent on real gold data.

Walks all `<data_root>/dane/przyklad_*/` directories and loads the three gold
JSON files in each. For every scalar leaf value, applies the normalizer
implied by the field's key name and asserts `normalize(n, value) == value`.

If this test fails, the normalizer is wrong -- fix the normalizer, never the
assertion, and never special-case a value to make the test pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lab.paths import data_root
from o2jcore.normalize.values import normalize

GOLD_FILENAMES = ["odwolanie.json", "pelnomocnictwo.json", "przelew.json"]

KEY_TO_NORMALIZER: dict[str, str] = {
    "data": "date_iso",
    "czynnosc_dzien": "date_iso",
    "data_operacji": "date_iso",
    "nip": "digits",
    "regon": "digits",
    "krs": "digits",
    "pesel": "digits",
    "na_rachunek": "nrb26",
    "z_rachunku": "nrb26",
    "numer_bzp": "bzp",
    "numer_ted": "ted",
    "kwota": "money",
    "czynnosc_powod_id": "enum_int",
    "przez-pelnomocnika": "enum_int",
    "prowadzacy_postepowanie": "enum_int",
}
DEFAULT_NORMALIZER = "text"


def _gold_files() -> list[Path]:
    root = data_root() / "dane"
    files: list[Path] = []
    for example_dir in sorted(root.glob("przyklad_*")):
        if not example_dir.is_dir():
            continue
        for filename in GOLD_FILENAMES:
            path = example_dir / filename
            if path.exists():
                files.append(path)
    return files


def _walk_leaves(obj: Any, path: str, out: list[tuple[str, str, Any]]) -> None:
    """Collect (json_path, key_name, value) for every scalar leaf."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                _walk_leaves(value, child_path, out)
            else:
                out.append((child_path, key, value))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            child_path = f"{path}[{idx}]"
            if isinstance(item, (dict, list)):
                _walk_leaves(item, child_path, out)
            else:
                out.append((child_path, path.rsplit(".", 1)[-1] if path else "", item))


def test_finds_all_180_gold_files():
    files = _gold_files()
    assert len(files) == 180, f"expected 180 gold files, found {len(files)}: {files[:5]}..."


def test_normalizers_idempotent_on_gold():
    files = _gold_files()
    assert len(files) == 180

    failures: list[str] = []

    for path in files:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        leaves: list[tuple[str, str, Any]] = []
        _walk_leaves(data, "", leaves)

        for json_path, key, value in leaves:
            if value is None:
                continue
            normalizer_name = KEY_TO_NORMALIZER.get(key, DEFAULT_NORMALIZER)
            try:
                result = normalize(normalizer_name, value)
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"{path}: {json_path} normalizer={normalizer_name!r} "
                    f"input={value!r} RAISED {exc!r}"
                )
                continue
            if result != value:
                failures.append(
                    f"{path}: {json_path} normalizer={normalizer_name!r} "
                    f"input={value!r} output={result!r}"
                )

    if failures:
        msg = "\n".join(failures)
        pytest.fail(f"{len(failures)} non-idempotent normalizer result(s):\n{msg}")
