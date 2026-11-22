"""Loads DocClassSpec trees from YAML config files.

`load_class_spec` parses one `configs/classes/*.yaml` file into a
`DocClassSpec`, resolving `enum:` references against the shared enum files in
`configs/enums/`. `load_all_classes` glob-loads every class YAML in a
directory, keyed by each spec's declared `id`.

Every malformed or incomplete YAML fails loudly: missing required keys, bad
types, dangling enum references, etc. all raise `ValueError` naming the
offending file. Nothing here is allowed to silently default or skip a field
-- a 4th document class is added purely by dropping in a new, correctly
shaped YAML file; any shape mistake must surface immediately as spec load
code, not as a mysterious failure three steps later.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import DocClassSpec, EnumSpec, FieldSpec, ListSpec

_REQUIRED_CLASS_KEYS = {"id", "title", "pdf_stem", "gold_stem", "fields"}
_REQUIRED_FIELD_KEYS = {"path", "kind"}
_VALID_KINDS = {"string", "integer", "float", "object"}


def _fail(path: Path, msg: str) -> None:
    raise ValueError(f"{path}: {msg}")


def _load_enum_map(enum_name: str, enums_dir: Path, class_path: Path) -> dict[int, str]:
    enum_path = enums_dir / f"{enum_name}.yaml"
    if not enum_path.exists():
        _fail(class_path, f"references unknown enum '{enum_name}' (expected {enum_path})")
    with enum_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict) or not raw:
        _fail(enum_path, "must parse to a non-empty mapping of {int: str}")
    result: dict[int, str] = {}
    for k, v in raw.items():
        if not isinstance(k, int) or isinstance(v, bool):
            _fail(enum_path, f"enum key {k!r} must be an integer")
        if not isinstance(v, str) or not v:
            _fail(enum_path, f"enum value for key {k!r} must be a non-empty string")
        result[k] = v
    return result


def _parse_field(raw: dict, class_path: Path) -> FieldSpec:
    if not isinstance(raw, dict):
        _fail(class_path, f"each field entry must be a mapping, got {raw!r}")
    missing = _REQUIRED_FIELD_KEYS - raw.keys()
    if missing:
        _fail(class_path, f"field entry {raw!r} is missing required keys: {sorted(missing)}")

    path = raw["path"]
    if not isinstance(path, str) or not path:
        _fail(class_path, f"field 'path' must be a non-empty string, got {path!r}")

    kind = raw["kind"]
    if kind not in _VALID_KINDS:
        _fail(class_path, f"field '{path}': kind {kind!r} must be one of {sorted(_VALID_KINDS)}")

    is_list = path.endswith("[]")

    nullable = raw.get("nullable", True)
    if not isinstance(nullable, bool):
        _fail(class_path, f"field '{path}': nullable must be a bool")

    normalizer = raw.get("normalizer", "identity")
    if not isinstance(normalizer, str):
        _fail(class_path, f"field '{path}': normalizer must be a string")

    fuzzy_threshold = raw.get("fuzzy_threshold", 90)
    if not isinstance(fuzzy_threshold, int) or isinstance(fuzzy_threshold, bool):
        _fail(class_path, f"field '{path}': fuzzy_threshold must be an int")

    description = raw.get("description", "")
    if not isinstance(description, str):
        _fail(class_path, f"field '{path}': description must be a string")

    derived_from = raw.get("derived_from")
    if derived_from is not None and not isinstance(derived_from, str):
        _fail(class_path, f"field '{path}': derived_from must be a string")

    list_spec = None
    raw_list_spec = raw.get("list_spec")
    if is_list:
        if raw_list_spec is None:
            _fail(class_path, f"field '{path}' ends in '[]' and requires a 'list_spec'")
        if not isinstance(raw_list_spec, dict):
            _fail(class_path, f"field '{path}': list_spec must be a mapping")
        lmin = raw_list_spec.get("min", 0)
        lmax = raw_list_spec.get("max")
        match_on = raw_list_spec.get("match_on", [])
        if not isinstance(lmin, int) or isinstance(lmin, bool):
            _fail(class_path, f"field '{path}': list_spec.min must be an int")
        if lmax is not None and (not isinstance(lmax, int) or isinstance(lmax, bool)):
            _fail(class_path, f"field '{path}': list_spec.max must be an int or null")
        if not isinstance(match_on, list) or not all(isinstance(x, str) for x in match_on):
            _fail(class_path, f"field '{path}': list_spec.match_on must be a list of strings")
        list_spec = ListSpec(min=lmin, max=lmax, match_on=list(match_on))
    elif raw_list_spec is not None:
        _fail(class_path, f"field '{path}' has a 'list_spec' but its path doesn't end in '[]'")

    enum_spec = None
    enum_name = raw.get("enum")
    enum_values = raw.get("enum_values")
    if enum_name is not None and enum_values is not None:
        _fail(class_path, f"field '{path}': cannot set both 'enum' and 'enum_values'")
    if enum_name is not None:
        if not isinstance(enum_name, str):
            _fail(class_path, f"field '{path}': enum must be a string naming an enum file")
        enum_role = raw.get("enum_role")
        if enum_role not in ("key", "label"):
            _fail(
                class_path,
                f"field '{path}': enum_role must be 'key' or 'label' when 'enum' is set",
            )
        # resolved lazily by the caller (needs enums_dir); stash the name for now
        enum_spec = EnumSpec(values=None, role=enum_role, inline_values=None)
        enum_spec._pending_enum_name = enum_name  # type: ignore[attr-defined]
    elif enum_values is not None:
        if not isinstance(enum_values, list) or not all(isinstance(x, str) for x in enum_values):
            _fail(class_path, f"field '{path}': enum_values must be a list of strings")
        enum_spec = EnumSpec(values=None, role=None, inline_values=list(enum_values))

    return FieldSpec(
        path=path,
        kind=kind,
        nullable=nullable,
        normalizer=normalizer,
        fuzzy_threshold=fuzzy_threshold,
        description=description,
        enum=enum_spec,
        derived_from=derived_from,
        list_spec=list_spec,
    )


def load_class_spec(path: Path, enums_dir: Path | None = None) -> DocClassSpec:
    """Parse one `configs/classes/*.yaml` file into a DocClassSpec.

    `enums_dir` defaults to the sibling `enums/` directory of `path`'s parent
    (i.e. `configs/classes/x.yaml` -> `configs/enums/`).
    """
    path = Path(path)
    if enums_dir is None:
        enums_dir = path.parent.parent / "enums"
    else:
        enums_dir = Path(enums_dir)

    if not path.exists():
        _fail(path, "file does not exist")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        _fail(path, "top-level YAML must be a mapping")

    missing = _REQUIRED_CLASS_KEYS - raw.keys()
    if missing:
        _fail(path, f"missing required top-level keys: {sorted(missing)}")

    raw_fields = raw["fields"]
    if not isinstance(raw_fields, list) or not raw_fields:
        _fail(path, "'fields' must be a non-empty list")

    fields = [_parse_field(rf, path) for rf in raw_fields]

    # resolve pending shared-enum references now that we know enums_dir
    for f in fields:
        if f.enum is not None and getattr(f.enum, "_pending_enum_name", None):
            enum_name = f.enum._pending_enum_name  # type: ignore[attr-defined]
            f.enum.values = _load_enum_map(enum_name, enums_dir, path)

    for key in ("id", "title", "pdf_stem", "gold_stem"):
        if not isinstance(raw[key], str) or not raw[key]:
            _fail(path, f"'{key}' must be a non-empty string")

    return DocClassSpec(
        id=raw["id"],
        title=raw["title"],
        pdf_stem=raw["pdf_stem"],
        gold_stem=raw["gold_stem"],
        fields=fields,
        source_path=str(path),
    )


def load_all_classes(directory: Path, enums_dir: Path | None = None) -> dict[str, DocClassSpec]:
    """Load every `*.yaml` file in `directory`, keyed by each spec's `id`."""
    directory = Path(directory)
    result: dict[str, DocClassSpec] = {}
    for yaml_path in sorted(directory.glob("*.yaml")):
        spec = load_class_spec(yaml_path, enums_dir=enums_dir)
        if spec.id in result:
            _fail(
                yaml_path,
                f"duplicate class id '{spec.id}' (already loaded from "
                f"{result[spec.id].source_path})",
            )
        result[spec.id] = spec
    return result
