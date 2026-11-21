"""Dataclasses describing one document class's schema, parsed from YAML.

These are the single source of truth that both the runtime Pydantic model
(`pydantic_build.build_model`) and the hand-rolled, fully-inlined JSON Schema
(`jsonschema_build.build_json_schema`) are generated from independently.

Nothing document-class-specific lives in this module or in the two builder
modules below it — a 4th document class is added purely by writing a new
YAML file under `configs/classes/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ListSpec:
    """Cardinality + alignment hint for a field that holds a list of objects."""

    min: int = 0
    max: int | None = None
    match_on: list[str] = field(default_factory=list)


@dataclass
class EnumSpec:
    """A resolved enum map, either shared (loaded from configs/enums/*.yaml)
    or inline (small, class-specific `enum_values` lists).

    `role` is only meaningful for a resolved {int: str} map:
      - "key": the field holds the integer key (e.g. czynnosc_powod_id)
      - "label": the field holds the string value (e.g. czynnosc_opis)
    For inline string enums (`enum_values`), role is ignored.
    """

    values: dict[int, str] | None  # resolved {key: label} map, or None for inline-string enums
    role: str | None = None  # "key" | "label" | None
    inline_values: list[str] | None = None  # for plain string enum_values (no key/label split)


@dataclass
class FieldSpec:
    """One leaf or container field in a document class's schema.

    `path` is the dotted path from the document root, with a trailing
    ``[]`` on a segment meaning "this key holds a list of objects"
    (e.g. ``Odwolujacy[].pelnomocnik.mail``).
    """

    path: str
    kind: str  # "string" | "integer" | "float" | "object" (object only for pure containers)
    nullable: bool = True
    normalizer: str = "identity"
    description: str = ""
    enum: EnumSpec | None = None
    derived_from: str | None = None
    list_spec: ListSpec | None = None  # set only on fields whose path ends in "[]"

    @property
    def segments(self) -> list[str]:
        return self.path.split(".")

    @property
    def key(self) -> str:
        """The final path segment, with any trailing [] stripped."""
        last = self.segments[-1]
        return last[:-2] if last.endswith("[]") else last

    @property
    def is_list(self) -> bool:
        return self.segments[-1].endswith("[]")


@dataclass
class DocClassSpec:
    """Full schema for one document class, as parsed from one YAML file."""

    id: str
    title: str
    pdf_stem: str
    gold_stem: str
    fields: list[FieldSpec]
    source_path: str = ""
