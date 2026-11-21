"""Builds a runtime Pydantic v2 model for one document class, directly from
its DocClassSpec -- never derived from the JSON Schema in
`jsonschema_build.py`.

Nested objects and nested list-item objects are themselves built with
`pydantic.create_model` (not a static class, and not `$ref` -- pydantic
resolves nested model references internally; the hand-rolled-JSON-Schema's
no-$ref constraint only applies to `jsonschema_build.py`).

Each leaf field's normalizer is wired in as a `field_validator(mode="before")`
that calls `o2jcore.normalize.values.normalize(name, value)` *before*
pydantic's own type coercion runs -- this lets a normalizer turn a raw,
loosely-typed LLM value (e.g. "15 000,00 zł") into the properly-typed value
(e.g. 15000.0) that the field's annotation then accepts, so a single
`Model.model_validate(raw_dict)` call simultaneously validates *and*
normalizes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model, field_validator

from o2jcore.normalize.values import normalize

from .models import DocClassSpec, FieldSpec
from .tree import LeafNode, ListNode, ObjectNode, build_tree

_KIND_TO_PY_TYPE: dict[str, type] = {
    "string": str,
    "integer": int,
    "float": float,
}


def _validator_entry(field_key: str, normalizer_name: str) -> Any:
    def _run(cls: Any, v: Any) -> Any:  # noqa: ANN401
        return normalize(normalizer_name, v)

    return field_validator(field_key, mode="before")(classmethod(_run))


def _enum_values(f: FieldSpec) -> list[Any] | None:
    """Mirror jsonschema_build's enum expansion so the Pydantic model and the
    JSON Schema accept exactly the same values."""
    enum = f.enum
    if enum is None:
        return None
    if enum.inline_values is not None:
        return list(enum.inline_values)
    if enum.values is not None:
        if enum.role == "key":
            return list(enum.values.keys())
        if enum.role == "label":
            return list(enum.values.values())
    return None


def _leaf_field_def(f: FieldSpec) -> tuple[Any, Any]:
    py_type = _KIND_TO_PY_TYPE[f.kind]
    annotation: Any = (py_type | None) if f.nullable else py_type
    values = _enum_values(f)
    if values:
        annotation = Literal[*values]
        if f.nullable:
            annotation = annotation | None
    return (annotation, ...)


def _build_model_for_object(name: str, node: ObjectNode) -> type[BaseModel]:
    field_defs: dict[str, tuple[Any, Any]] = {}
    validators: dict[str, Any] = {}

    for key, child in node.children.items():
        if isinstance(child, LeafNode):
            field_defs[key] = _leaf_field_def(child.field)
            validators[f"_normalize_{key}"] = _validator_entry(key, child.field.normalizer)
        elif isinstance(child, ListNode):
            item_model = _build_model_for_object(f"{name}__{key}Item", child.item)
            field_defs[key] = (list[item_model], ...)
        else:  # ObjectNode: plain nested container, always required+non-null
            sub_model = _build_model_for_object(f"{name}__{key}", child)
            field_defs[key] = (sub_model, ...)

    return create_model(
        name,
        __config__=ConfigDict(extra="forbid"),
        __validators__=validators or None,
        **field_defs,
    )


def build_model(spec: DocClassSpec) -> type[BaseModel]:
    """Build a runtime pydantic v2 model for one document class."""
    root = build_tree(spec)
    base_name = "".join(part.capitalize() for part in spec.id.split("_"))
    return _build_model_for_object(f"{base_name}Model", root)
