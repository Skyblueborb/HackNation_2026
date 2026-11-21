"""Flatten JSON documents into {canonical_leaf_path: scalar} maps, driven by
a `DocClassSpec` (see `o2jcore.spec.models`).

Two entry points matter:

- `flatten()` / `flatten_fields()`: single-document flatten. List-of-object
  fields are numbered in the list's own (natural) order. This is what you
  want when there is no "other side" to align against -- hand-built test
  fixtures, a round-trip sanity check on one gold file, or the internal
  per-element flattening `match.element_similarity` does to compute a
  similarity score (alignment doesn't apply there; it's exactly what
  `element_similarity` is used to *compute*).

- `flatten_pair()`: the two-sided entry point `evaluate_run` uses. It walks
  pred and gold *together*; at every list-of-object field it calls
  `match.greedy_align()` to decide which pred element corresponds to which
  gold element, and only *after* that alignment does it assign the `[i]`
  index that both sides share. This is what guarantees list element order
  never affects scoring.

Both paths share the same tree-walking machinery (`_Node`, `_build_tree`),
built once from a spec's flat list of `FieldSpec`s.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from o2jcore.spec.models import DocClassSpec, FieldSpec, ListSpec, split_segment

JsonScalar = str | int | float | bool | None

_INDEX_RE = re.compile(r"\[\d+\]")


def canonicalize_path(path: str) -> str:
    """Strip concrete list indices from a flattened leaf path, e.g.
    'Odwolujacy[0].nip' -> 'Odwolujacy[].nip'. Idempotent. Leaves '!extra:'
    paths' own (possibly index-bearing) suffix canonicalized the same way.
    """
    return _INDEX_RE.sub("[]", path)


@dataclass
class _Node:
    children: dict[str, "_Node"] = field(default_factory=dict)
    is_list: bool = False
    list_spec: ListSpec | None = None
    leaf_spec: FieldSpec | None = None  # set only for scalar leaves

    @property
    def is_leaf(self) -> bool:
        return self.leaf_spec is not None and not self.children and not self.is_list


def _build_tree(fields: list[FieldSpec]) -> _Node:
    root = _Node()
    for f in fields:
        segs = f.segments
        node = root
        for i, seg in enumerate(segs):
            is_last = i == len(segs) - 1
            key, seg_is_list = split_segment(seg)
            child = node.children.setdefault(key, _Node())
            if seg_is_list:
                child.is_list = True
            if is_last:
                if f.kind == "object":
                    # this field entry *is* the list/object container itself
                    child.list_spec = f.list_spec
                else:
                    child.leaf_spec = f
            node = child
    return root


def _collect_extra(val: Any, path: str, out: dict[str, JsonScalar]) -> None:
    """Deep-flatten a value that has no spec coverage at all, so it's never
    silently dropped -- just routed under a '!extra:' path."""
    if isinstance(val, dict):
        if not val:
            out[path] = None
        for k, v in val.items():
            _collect_extra(v, f"{path}.{k}", out)
    elif isinstance(val, list):
        if not val:
            out[path] = None
        for i, v in enumerate(val):
            _collect_extra(v, f"{path}[{i}]", out)
    else:
        out[path] = val


def relative_fields(all_fields: list[FieldSpec], list_path: str) -> dict[str, FieldSpec]:
    """FieldSpecs describing one list field's *element* shape, keyed and
    path-rewritten relative to that list (prefix stripped), e.g. for
    list_path='mocodawca[]', 'mocodawca[].data.nip' -> key 'data.nip' with a
    FieldSpec whose .path is also 'data.nip'. Excludes the list field's own
    container entry."""
    prefix = f"{list_path}."
    out: dict[str, FieldSpec] = {}
    for f in all_fields:
        if f.path == list_path:
            continue
        if f.path.startswith(prefix):
            rel_path = f.path[len(prefix) :]
            rel_field = copy.copy(f)
            rel_field.path = rel_path
            out[rel_path] = rel_field
    return out


def flatten_fields(
    obj: dict, fields: list[FieldSpec], *, prefix_extra: bool = True, path_prefix: str = ""
) -> dict[str, JsonScalar]:
    """Single-document flatten over an explicit field list (used directly by
    `flatten()`, and reused by `match.element_similarity` to flatten one
    list element against a relativized field subset)."""
    tree = _build_tree(fields)
    out: dict[str, JsonScalar] = {}
    _flatten_node_single(obj if isinstance(obj, dict) else {}, tree, path_prefix, out, prefix_extra)
    return out


def _flatten_node_single(
    obj: dict, node: _Node, prefix: str, out: dict[str, JsonScalar], prefix_extra: bool
) -> None:
    present = set(obj.keys()) if isinstance(obj, dict) else set()
    for key, child in node.children.items():
        cpath = f"{prefix}.{key}" if prefix else key
        val = obj.get(key) if isinstance(obj, dict) else None
        if child.is_list:
            lst = val if isinstance(val, list) else []
            for i, elem in enumerate(lst):
                elem_dict = elem if isinstance(elem, dict) else {}
                _flatten_node_single(elem_dict, child, f"{cpath}[{i}]", out, prefix_extra)
        elif child.children:
            sub = val if isinstance(val, dict) else {}
            _flatten_node_single(sub, child, cpath, out, prefix_extra)
        else:
            out[cpath] = val
    if prefix_extra:
        extra_keys = present - set(node.children.keys())
        for key in sorted(extra_keys):
            extra_path = f"!extra:{prefix}.{key}" if prefix else f"!extra:{key}"
            _collect_extra(obj[key], extra_path, out)


def flatten(obj: dict, spec: DocClassSpec, *, prefix_extra: bool = True) -> dict[str, JsonScalar]:
    """Flatten a whole document against its DocClassSpec, single-sided
    (list order preserved as given -- no pred/gold alignment)."""
    return flatten_fields(obj, spec.fields, prefix_extra=prefix_extra)


def flatten_pair(
    pred_obj: dict, gold_obj: dict, spec: DocClassSpec
) -> tuple[dict[str, JsonScalar], dict[str, JsonScalar]]:
    """Flatten pred and gold together. Every list-of-object field is aligned
    via `match.greedy_align` (imported lazily to avoid a module-load cycle,
    since match.py imports flatten.py for its own single-sided flattening)
    BEFORE either side's list indices are finalized, so pred/gold element
    order never affects the resulting leaf paths."""
    from lab.eval import match as _match

    tree = _build_tree(spec.fields)
    pred_out: dict[str, JsonScalar] = {}
    gold_out: dict[str, JsonScalar] = {}
    _flatten_pair_node(
        pred_obj if isinstance(pred_obj, dict) else {},
        gold_obj if isinstance(gold_obj, dict) else {},
        tree,
        "",
        "",
        pred_out,
        gold_out,
        spec.fields,
        _match,
    )
    return pred_out, gold_out


def _flatten_pair_node(
    pred_obj: dict,
    gold_obj: dict,
    node: _Node,
    out_prefix: str,
    canon_prefix: str,
    pred_out: dict[str, JsonScalar],
    gold_out: dict[str, JsonScalar],
    all_fields: list[FieldSpec],
    match_mod: Any,
) -> None:
    """`out_prefix` carries real list indices (what actually lands in
    pred_out/gold_out's keys); `canon_prefix` mirrors it but always uses
    bare '[]' for list segments, matching how FieldSpec.path is spelled in
    the YAML specs -- needed so `relative_fields` can look up a nested
    list's own element fields correctly however deep the nesting goes
    (e.g. mocodawca[].podpisujacy[])."""
    pred_present = set(pred_obj.keys())
    gold_present = set(gold_obj.keys())
    for key, child in node.children.items():
        out_cpath = f"{out_prefix}.{key}" if out_prefix else key
        canon_cpath = f"{canon_prefix}.{key}" if canon_prefix else key
        pred_val = pred_obj.get(key)
        gold_val = gold_obj.get(key)
        if child.is_list:
            pred_list = pred_val if isinstance(pred_val, list) else []
            gold_list = gold_val if isinstance(gold_val, list) else []
            local_fields = relative_fields(all_fields, f"{canon_cpath}[]")
            pairs = match_mod.greedy_align(pred_list, gold_list, child.list_spec, local_fields)
            for i, (pidx, gidx) in enumerate(pairs):
                p_elem = pred_list[pidx] if pidx is not None else {}
                g_elem = gold_list[gidx] if gidx is not None else {}
                p_elem = p_elem if isinstance(p_elem, dict) else {}
                g_elem = g_elem if isinstance(g_elem, dict) else {}
                _flatten_pair_node(
                    p_elem,
                    g_elem,
                    child,
                    f"{out_cpath}[{i}]",
                    f"{canon_cpath}[]",
                    pred_out,
                    gold_out,
                    all_fields,
                    match_mod,
                )
        elif child.children:
            sub_pred = pred_val if isinstance(pred_val, dict) else {}
            sub_gold = gold_val if isinstance(gold_val, dict) else {}
            _flatten_pair_node(
                sub_pred, sub_gold, child, out_cpath, canon_cpath, pred_out, gold_out, all_fields, match_mod
            )
        else:
            pred_out[out_cpath] = pred_val
            gold_out[out_cpath] = gold_val

    expected = set(node.children.keys())
    for key in sorted(pred_present - expected):
        extra_path = f"!extra:{out_prefix}.{key}" if out_prefix else f"!extra:{key}"
        _collect_extra(pred_obj[key], extra_path, pred_out)
    for key in sorted(gold_present - expected):
        extra_path = f"!extra:{out_prefix}.{key}" if out_prefix else f"!extra:{key}"
        _collect_extra(gold_obj[key], extra_path, gold_out)
