"""Builds an ordered nested tree from a DocClassSpec's flat, dotted-path field list.

Both `pydantic_build.build_model` and `jsonschema_build.build_json_schema` walk
this same tree independently -- it is the shared "parsed structure" step, but
each builder still produces its artifact (Pydantic model vs. inlined JSON
Schema) on its own, per the no-derivation-from-each-other requirement.

A YAML `fields:` entry declares either:
  - a leaf (scalar) field: path has no "[]" segment at all, or
  - a list-of-objects field: its own path ends in "[]" (e.g. "Odwolujacy[]").

Everything else -- plain nested objects like "OdwolanieKIO" or
"mocodawca[].data" -- is *inferred* purely from the dotted paths of the
leaf/list fields that reference it; it needs no YAML entry of its own, and no
document-class-specific code exists to special-case it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .models import DocClassSpec, FieldSpec, split_segment


@dataclass
class LeafNode:
    field: FieldSpec


@dataclass
class ListNode:
    field: FieldSpec  # the field describing the list itself (list_spec, description, ...)
    item: "ObjectNode"


@dataclass
class ObjectNode:
    children: dict[str, "LeafNode | ListNode | ObjectNode"] = dc_field(default_factory=dict)


def build_tree(spec: DocClassSpec) -> ObjectNode:
    """Build the root ObjectNode for a document class, preserving YAML field order."""
    root = ObjectNode()
    for f in spec.fields:
        segments = f.segments
        node: ObjectNode = root
        for i, segment in enumerate(segments):
            key, is_list_segment = split_segment(segment)
            is_last = i == len(segments) - 1

            if is_last:
                if is_list_segment:
                    if key not in node.children:
                        node.children[key] = ListNode(field=f, item=ObjectNode())
                    existing = node.children[key]
                    if not isinstance(existing, ListNode):
                        raise ValueError(
                            f"{spec.source_path}: field path '{f.path}' conflicts with an "
                            f"earlier non-list node at key '{key}'"
                        )
                else:
                    if key in node.children:
                        raise ValueError(
                            f"{spec.source_path}: duplicate field path '{f.path}'"
                        )
                    node.children[key] = LeafNode(field=f)
            else:
                if key not in node.children:
                    if is_list_segment:
                        # Intermediate list segment referenced before its own
                        # field entry was declared -- not supported, every
                        # list container must have its own explicit entry
                        # (it carries list_spec) earlier in the fields list.
                        raise ValueError(
                            f"{spec.source_path}: list segment '{segment}' in path "
                            f"'{f.path}' has no preceding field entry declaring it"
                        )
                    node.children[key] = ObjectNode()
                existing = node.children[key]
                if is_list_segment:
                    if not isinstance(existing, ListNode):
                        raise ValueError(
                            f"{spec.source_path}: segment '{segment}' in path '{f.path}' "
                            f"expected a list container at key '{key}'"
                        )
                    node = existing.item
                else:
                    if not isinstance(existing, ObjectNode):
                        raise ValueError(
                            f"{spec.source_path}: segment '{segment}' in path '{f.path}' "
                            f"expected a plain object container at key '{key}'"
                        )
                    node = existing
    return root
