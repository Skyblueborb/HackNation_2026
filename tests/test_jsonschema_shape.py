"""Structural invariants for the hand-rolled, fully-inlined JSON Schema
produced by `jsonschema_build.build_json_schema`.

These are the properties a llama.cpp-grammar-driven generator depends on:
no $ref/$defs anywhere (grammars can't follow them), additionalProperties
false + required == properties at every object level (forces every key to
be emitted, in a fixed order), every leaf nullable via its type union, and
stable key order matching the YAML spec.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from o2jcore.spec.jsonschema_build import build_json_schema
from o2jcore.spec.loader import load_all_classes

REPO_ROOT = Path(__file__).resolve().parents[1]
_CLASS_IDS = ("odwolanie", "pelnomocnictwo", "potwierdzenie_przelewu")


@pytest.fixture(scope="module")
def specs():
    return load_all_classes(REPO_ROOT / "configs" / "classes")


def _walk(node):
    """Yield every dict found anywhere in the schema, including nested ones."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _is_container(schema: dict) -> bool:
    t = schema.get("type")
    if t == "object":
        return True
    if isinstance(t, list) and "array" in t:
        return True
    return False


def _container_depth(schema: dict) -> int:
    """Depth in terms of nested *object* levels. An array doesn't add its own
    level -- its items are at the same conceptual depth as the array field
    itself, since the array is just "N copies of the object inside it", not
    an extra level of key-nesting. This matches how a human would read the
    structure (and lets a field like pelnomocnictwo's `mocodawca[].podpisujacy[]`
    -- a list nested inside a list item, which genuinely occurs in the gold
    data -- count as 3 object levels deep rather than 5)."""
    t = schema.get("type")
    if t == "object":
        child_depths = [
            _container_depth(v) for v in schema["properties"].values() if _is_container(v)
        ]
        return 1 + (max(child_depths) if child_depths else 0)
    if isinstance(t, list) and "array" in t:
        return _container_depth(schema["items"])
    return 0


def _assert_object_invariants(schema: dict, path: str):
    """Recursively assert additionalProperties/required invariants on every
    object-type node, and that every leaf's type union includes null."""
    t = schema.get("type")
    if t == "object":
        assert schema.get("additionalProperties") is False, (
            f"{path}: object node missing additionalProperties: false"
        )
        props = schema.get("properties", {})
        required = schema.get("required", [])
        assert set(required) == set(props.keys()), (
            f"{path}: required {sorted(required)} != properties {sorted(props.keys())}"
        )
        for key, child in props.items():
            _assert_object_invariants(child, f"{path}.{key}")
    elif isinstance(t, list) and "array" in t:
        assert "null" in t, f"{path}: array type union missing null: {t}"
        _assert_object_invariants(schema["items"], f"{path}[]")
    else:
        # leaf
        assert isinstance(t, list), f"{path}: leaf type must be a list, got {t!r}"
        assert "null" in t, f"{path}: leaf type union missing null: {t}"


@pytest.mark.parametrize("class_id", _CLASS_IDS)
def test_no_ref_or_defs_anywhere(specs, class_id):
    schema = build_json_schema(specs[class_id])
    for node in _walk(schema):
        assert "$ref" not in node, f"found $ref in schema for {class_id}: {node}"
        assert "$defs" not in node, f"found $defs in schema for {class_id}: {node}"


@pytest.mark.parametrize("class_id", _CLASS_IDS)
def test_additional_properties_and_required_everywhere(specs, class_id):
    schema = build_json_schema(specs[class_id])
    _assert_object_invariants(schema, class_id)


@pytest.mark.parametrize("class_id", _CLASS_IDS)
def test_nesting_depth_bounded(specs, class_id):
    schema = build_json_schema(specs[class_id])
    depth = _container_depth(schema)
    assert depth <= 4, f"{class_id}: nesting depth {depth} exceeds 4"


@pytest.mark.parametrize("class_id", _CLASS_IDS)
def test_top_level_key_order_matches_yaml(specs, class_id):
    spec = specs[class_id]
    schema = build_json_schema(spec)

    expected_order = []
    for f in spec.fields:
        key = f.segments[0]
        if key.endswith("[]"):
            key = key[:-2]
        if key not in expected_order:
            expected_order.append(key)

    actual_order = list(schema["properties"].keys())
    assert actual_order == expected_order, (
        f"{class_id}: top-level key order {actual_order} != YAML order {expected_order}"
    )
