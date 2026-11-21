"""Minimal OCR smoke benchmark (Phase B, deliberately NOT the full grid).

Sanity-checks that Tesseract + the Polish language pack produce reasonable
text on a small, class-balanced sample of training pages, at exactly one
engine (tesseract 'pol') and one synthetic noise level ('light'). This is
intentionally the full extent of Phase B for now -- see AI/PLAN.md section
8A for the (deferred) full engine/noise-level grid.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jiwer

from o2jcore.ocr.smoke import degrade_light, render_page_png, run_tesseract
from o2jcore.text.pdf_text import extract_pages

SET_NAME_PREFIX = "przyklad_"

# document class -> (pdf filename, gold json filename)
_CLASSES: list[tuple[str, str]] = [
    ("odwolanie", "odwolanie.pdf"),
    ("pelnomocnictwo", "pelnomocnictwo.pdf"),
    ("potwierdzenie_przelewu", "potwierdzenie_przelewu.pdf"),
]


def _set_number(name: str) -> int:
    return int(name[len(SET_NAME_PREFIX) :])


def _choose_sets(data_root: Path, work_root: Path, n_pages: int) -> tuple[list[str], str]:
    """Pick the dev sets to draw pages from, and report where they came from."""
    splits_path = Path(work_root) / "splits.json"
    if splits_path.exists():
        with splits_path.open("r", encoding="utf-8") as f:
            split_data = json.load(f)
        dev_sets = sorted(split_data["dev"], key=_set_number)
        source = "dev-split"
    else:
        sets_dir = Path(data_root) / "dane"
        dev_sets = sorted(
            (p.name for p in sets_dir.glob(f"{SET_NAME_PREFIX}*") if p.is_dir()),
            key=_set_number,
        )
        source = "fallback-first-sets"

    if not dev_sets:
        raise RuntimeError(f"no training sets found for sampling under {data_root}")

    # Spread n_pages roughly evenly across the 3 classes.
    n_classes = len(_CLASSES)
    base = n_pages // n_classes
    extra = n_pages % n_classes
    per_class = [base + (1 if i < extra else 0) for i in range(n_classes)]

    needed = sum(per_class)
    if needed > len(dev_sets):
        raise RuntimeError(
            f"need {needed} distinct sets but only {len(dev_sets)} available "
            f"(source={source})"
        )

    chosen_sets = dev_sets[:needed]
    return chosen_sets, source


def _cer(reference: str, hypothesis: str) -> float:
    reference = reference or ""
    hypothesis = hypothesis or ""
    if reference.strip() == "":
        # No usable ground truth characters to compare against.
        return float("nan")
    return float(jiwer.cer(reference, hypothesis))


def run_smoke_benchmark(
    data_root: Path,
    work_root: Path,
    *,
    n_pages: int = 8,
    seed: int = 42,
    tessdata_prefix: str | None = None,
) -> dict[str, Any]:
    """Run the minimal OCR smoke check and write/return its results.

    Picks `n_pages` pages (page 1 of distinct sets), roughly evenly spread
    across the 3 document classes, from the dev split (or, if no split
    exists yet, the lowest-numbered sets as a documented fallback). For
    each page: extracts ground-truth text, renders a clean 300dpi PNG, OCRs
    both the clean render and a 'light'-degraded version with Tesseract
    ('pol'), and computes CER against ground truth for both.
    """
    data_root = Path(data_root)
    work_root = Path(work_root)

    n_classes = len(_CLASSES)
    base = n_pages // n_classes
    extra = n_pages % n_classes
    per_class = [base + (1 if i < extra else 0) for i in range(n_classes)]

    chosen_sets, source = _choose_sets(data_root, work_root, n_pages)

    results: list[dict[str, Any]] = []
    set_idx = 0
    for (cls_name, pdf_filename), count in zip(_CLASSES, per_class):
        for _ in range(count):
            set_name = chosen_sets[set_idx]
            set_idx += 1

            pdf_path = data_root / "dane" / set_name / pdf_filename
            pages = extract_pages(pdf_path, "pdfplumber")
            gt_text = pages[0].text

            clean_img = render_page_png(pdf_path, 1, dpi=300)
            clean_text = run_tesseract(
                clean_img, lang="pol", tessdata_prefix=tessdata_prefix
            )

            light_img = degrade_light(clean_img, seed=seed)
            light_text = run_tesseract(
                light_img, lang="pol", tessdata_prefix=tessdata_prefix
            )

            cer_clean = _cer(gt_text, clean_text)
            cer_light = _cer(gt_text, light_text)

            results.append(
                {
                    "set": set_name,
                    "class": cls_name,
                    "page": 1,
                    "gt_chars": len(gt_text),
                    "cer_clean": cer_clean,
                    "cer_light": cer_light,
                }
            )

    valid_clean = [r["cer_clean"] for r in results if r["cer_clean"] == r["cer_clean"]]
    valid_light = [r["cer_light"] for r in results if r["cer_light"] == r["cer_light"]]
    mean_cer_clean = sum(valid_clean) / len(valid_clean) if valid_clean else float("nan")
    mean_cer_light = sum(valid_light) / len(valid_light) if valid_light else float("nan")

    out = {
        "n_pages": len(results),
        "source": source,
        "results": results,
        "mean_cer_clean": mean_cer_clean,
        "mean_cer_light": mean_cer_light,
    }

    out_dir = work_root / "ocr_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")

    return out
