"""Validates that every gold JSON file in the hackathon dataset parses
cleanly through the runtime Pydantic model generated from the matching
DocClassSpec YAML -- the end-to-end check that the declarative spec actually
matches reality, not just that it loads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from lab.paths import data_root
from o2jcore.spec.jsonschema_build import build_json_schema
from o2jcore.spec.loader import load_all_classes
from o2jcore.spec.models import DocClassSpec, EnumSpec, FieldSpec
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


# --- enum constraints: Pydantic and JSON Schema must agree -------------------


def test_pydantic_model_enforces_enum_values():
    spec = DocClassSpec(
        id="tiny",
        title="Tiny",
        pdf_stem="tiny",
        gold_stem="tiny",
        fields=[
            FieldSpec(
                path="kind",
                kind="string",
                nullable=True,
                normalizer="text",
                enum=EnumSpec(values=None, role=None, inline_values=["a", "b"]),
            )
        ],
    )
    model = build_model(spec)

    assert model.model_validate({"kind": "a"}).kind == "a"
    assert model.model_validate({"kind": None}).kind is None
    with pytest.raises(ValidationError):
        model.model_validate({"kind": "c"})


def _literals_in_annotation(ann) -> set:
    if get_origin(ann) is Literal:
        return set(get_args(ann))
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return _literals_in_model(ann)
    out: set = set()
    for arg in get_args(ann):
        if arg is type(None):
            out.add(None)
            continue
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            out |= _literals_in_model(arg)
        else:
            out |= _literals_in_annotation(arg)
    return out


def _literals_in_model(model) -> set:
    out: set = set()
    for field in model.model_fields.values():
        out |= _literals_in_annotation(field.annotation)
    return out


def _schema_enums(node) -> set:
    out: set = set()
    if isinstance(node, dict):
        if "enum" in node:
            out.update(node["enum"])
        for value in node.values():
            out |= _schema_enums(value)
    elif isinstance(node, list):
        for value in node:
            out |= _schema_enums(value)
    return out


def test_pydantic_enum_values_match_json_schema(specs):
    checked = 0
    for cid in _CLASS_IDS:
        model = build_model(specs[cid])
        expected = _schema_enums(build_json_schema(specs[cid]))
        if not expected:
            continue
        checked += 1
        assert _literals_in_model(model) == expected, f"{cid}: Pydantic/Schema enum mismatch"
    assert checked == 2, f"expected enum fields in 2 specs, found {checked}"

    # A TypeAdapter on a constrained field rejects an out-of-enum value.
    odwolanie = build_model(specs["odwolanie"])
    field = odwolanie.model_fields["OdwolanieKIO"].annotation.model_fields["czynnosc_opis"]
    with pytest.raises(ValidationError):
        TypeAdapter(field.annotation).validate_python("not a real label")
