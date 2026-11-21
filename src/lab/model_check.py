"""Document selection for the `lab model-check` harness.

This module owns where benchmark documents come from. It deliberately does not
run OCR or LLMs; those probes are added by later tasks in the same module.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab import paths
from o2jcore.spec.loader import load_all_classes

_SCAN_DIR_TO_CLASS = {
    "odwolania": "odwolanie",
    "pelnomocnictwa": "pelnomocnictwo",
    "potwierdzenia": "potwierdzenie_przelewu",
}


@dataclass(frozen=True)
class DocumentCase:
    set_id: str
    pdf: Path
    gold: Path
    class_id: str
    corpus: str
    has_text_layer: bool


def _specs() -> dict[str, Any]:
    return load_all_classes(paths.configs_root() / "classes")


def discover_sets(data_root: Path, corpus: str) -> list[str]:
    """List set ids for the requested corpus in deterministic order."""
    dane = paths.validate_data_root(data_root) / "dane"
    set_ids: list[str] = []
    if corpus in ("przyklad", "all"):
        set_ids.extend(
            sorted(
                (p.name for p in dane.glob("przyklad_*") if p.is_dir()),
                key=lambda name: int(name.split("_")[1]),
            )
        )
    if corpus in ("skany", "all"):
        for dir_name in sorted(_SCAN_DIR_TO_CLASS):
            scan_root = dane / "skany" / dir_name
            for pdf in sorted(scan_root.glob("*/*.pdf")):
                set_ids.append(f"skany_{dir_name}_{pdf.parent.name}")
    return set_ids


def _case_for_pdf(pdf: Path, dane: Path) -> DocumentCase:
    try:
        rel = pdf.resolve().relative_to(dane.resolve())
    except ValueError as exc:
        raise ValueError(f"PDF outside data_root: {pdf}") from exc
    parts = rel.parts
    if parts[0] == "skany":
        if len(parts) != 4 or parts[1] not in _SCAN_DIR_TO_CLASS:
            raise ValueError(f"unrecognised scan path: {pdf}")
        dir_name, scan_id = parts[1], parts[2]
        return DocumentCase(
            set_id=f"skany_{dir_name}_{scan_id}",
            pdf=pdf,
            gold=pdf.with_suffix(".json"),
            class_id=_SCAN_DIR_TO_CLASS[dir_name],
            corpus="skany",
            has_text_layer=False,
        )
    if len(parts) == 2 and parts[0].startswith("przyklad_"):
        for spec in _specs().values():
            if pdf.stem == spec.pdf_stem:
                return DocumentCase(
                    set_id=parts[0],
                    pdf=pdf,
                    gold=dane / parts[0] / f"{spec.gold_stem}.json",
                    class_id=spec.id,
                    corpus="przyklad",
                    has_text_layer=True,
                )
    raise ValueError(f"unrecognised PDF path under data_root: {pdf}")


def _cases_for_set(set_id: str, dane: Path) -> list[DocumentCase]:
    if set_id.startswith("skany_"):
        _, dir_name, scan_id = set_id.split("_", 2)
        pdf = dane / "skany" / dir_name / scan_id / f"{scan_id}.pdf"
        if not pdf.is_file():
            return []
        return [_case_for_pdf(pdf, dane)]
    cases: list[DocumentCase] = []
    for spec in _specs().values():
        pdf = dane / set_id / f"{spec.pdf_stem}.pdf"
        if pdf.is_file():
            cases.append(_case_for_pdf(pdf, dane))
    return cases


def select_documents(
    data_root: Path,
    *,
    corpus: str,
    count: int,
    random_sample: bool,
    seed: int,
    sets: list[str] | None,
    pdf_paths: list[Path] | None,
) -> list[DocumentCase]:
    """Resolve CLI selection options into concrete document cases."""
    dane = paths.validate_data_root(data_root) / "dane"
    if pdf_paths:
        return [_case_for_pdf(pdf, dane) for pdf in pdf_paths]
    if sets:
        selected = list(sets)
    else:
        pool = discover_sets(data_root, corpus)
        if count > 0 and count < len(pool):
            selected = random.Random(seed).sample(pool, count) if random_sample else pool[:count]
        else:
            selected = pool
    cases: list[DocumentCase] = []
    for set_id in selected:
        cases.extend(_cases_for_set(set_id, dane))
    return cases
