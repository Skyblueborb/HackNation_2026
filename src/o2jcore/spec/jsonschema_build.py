"""Builds a fully-inlined, llama.cpp-grammar-friendly JSON Schema for one
document class, directly from its DocClassSpec -- never from the Pydantic
model built by `pydantic_build.py` (that would reintroduce `$defs`/`$ref`
since `model_json_schema()` always emits those for nested models).

Every object node is `additionalProperties: false` with a `required` list
covering every one of its properties (every field is "required" in the JSON
Schema sense; nullability is expressed via the type union instead) -- this is
what forces a llama.cpp grammar derived from this schema to always emit every
key, in spec order, giving stable generation order.
"""

from __future__ import annotations

from .models import DocClassSpec, FieldSpec
from .tree import LeafNode, ListNode, ObjectNode, build_tree

_KIND_TO_JSON_TYPE = {
    "string": "string",
    "integer": "integer",
    "float": "number",
}


def _leaf_schema(f: FieldSpec) -> dict:
    json_type = _KIND_TO_JSON_TYPE[f.kind]
    schema: dict = {"type": [json_type, "null"]}
    if f.description:
        schema["description"] = f.description

    if f.enum is not None:
        if f.enum.inline_values is not None:
            schema["enum"] = [*f.enum.inline_values, None]
        elif f.enum.values is not None:
            if f.enum.role == "key":
                schema["enum"] = [*f.enum.values.keys(), None]
            else:  # "label"
                schema["enum"] = [*f.enum.values.values(), None]
    return schema


def _object_schema(node: ObjectNode) -> dict:
    properties: dict = {}
    for key, child in node.children.items():
        properties[key] = _node_schema(child)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _list_schema(node: ListNode) -> dict:
    f = node.field
    items = _object_schema(node.item)
    schema: dict = {"type": ["array", "null"], "items": items}
    if f.description:
        schema["description"] = f.description
    if f.list_spec is not None:
        schema["minItems"] = f.list_spec.min
        if f.list_spec.max is not None:
            schema["maxItems"] = f.list_spec.max
    return schema


def _node_schema(node: LeafNode | ListNode | ObjectNode) -> dict:
    if isinstance(node, LeafNode):
        return _leaf_schema(node.field)
    if isinstance(node, ListNode):
        return _list_schema(node)
    return _object_schema(node)


def build_json_schema(spec: DocClassSpec) -> dict:
    """Fully-inlined object schema for one document class. No $ref, no $defs,
    anywhere, at any depth. See module docstring for the invariants enforced.
    """
    root = build_tree(spec)
    schema = _object_schema(root)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": spec.title,
        **schema,
    }
    return schema
