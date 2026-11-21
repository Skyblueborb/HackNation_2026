"""Tests for the minimal OCR smoke check (Phase B, deliberately small).

Degradation determinism is always tested. Anything invoking the real
`tesseract` binary with the Polish language pack is skipped unless
`tesseract` is on PATH and `pol` is in `tesseract --list-langs`.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from lab import paths
from lab.ocr_smoke import run_smoke_benchmark
from o2jcore.ocr.smoke import degrade_light, render_page_png, run_tesseract

DATA_ROOT = paths.data_root()
DANE = DATA_ROOT / "dane"

TESSDATA_PREFIX = os.environ.get(
    "TESSDATA_PREFIX",
    str(paths.REPO_ROOT / "models" / "tessdata_best"),
)


def _tesseract_pol_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = TESSDATA_PREFIX
    try:
        proc = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            env=env,
            timeout=10,
        )
    except Exception:
        return False
    langs = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
        "utf-8", errors="replace"
    )
    return "pol" in langs.splitlines() or "\npol\n" in ("\n" + langs)


TESSERACT_POL_AVAILABLE = _tesseract_pol_available()

requires_tesseract_pol = pytest.mark.skipif(
    not TESSERACT_POL_AVAILABLE,
    reason="tesseract binary with 'pol' language data not available",
)


def _make_test_image() -> Image.Image:
    rng = np.random.default_rng(0)
    arr = (rng.random((40, 60, 3)) * 255).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


def test_degrade_light_deterministic_same_seed() -> None:
    img = _make_test_image()
    out1 = degrade_light(img, seed=42)
    out2 = degrade_light(img, seed=42)
    assert np.array_equal(np.asarray(out1), np.asarray(out2))


def test_degrade_light_different_for_different_seeds() -> None:
    img = _make_test_image()
    out1 = degrade_light(img, seed=42)
    out2 = degrade_light(img, seed=43)
    assert not np.array_equal(np.asarray(out1), np.asarray(out2))


@requires_tesseract_pol
def test_run_tesseract_recognizes_polish_text_from_real_pdf() -> None:
    pdf_path = DANE / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    assert pdf_path.exists(), f"missing fixture {pdf_path}"

    img = render_page_png(pdf_path, 1, dpi=300)
    text = run_tesseract(img, lang="pol", tessdata_prefix=TESSDATA_PREFIX)

    # From przyklad_01/przelew.json: na_rachunek starts with 684382230...
    normalized = text.replace(" ", "").replace("\n", "").replace("\r", "")
    assert "684382230" in normalized, f"expected account digits not found in OCR text: {text!r}"


@requires_tesseract_pol
def test_run_smoke_benchmark_three_pages() -> None:
    work_root = paths.work_root()
    result = run_smoke_benchmark(
        DATA_ROOT,
        work_root,
        n_pages=3,
        seed=42,
        tessdata_prefix=TESSDATA_PREFIX,
    )

    assert len(result["results"]) == 3
    assert result["n_pages"] == 3
    assert result["source"] in ("dev-split", "fallback-first-sets")

    mean_cer_clean = result["mean_cer_clean"]
    assert mean_cer_clean == mean_cer_clean, "mean_cer_clean is NaN"
    assert mean_cer_clean < 0.15, (
        f"mean_cer_clean={mean_cer_clean!r} is suspiciously high; "
        "ground-truth extraction or the Polish language pack may be broken"
    )
