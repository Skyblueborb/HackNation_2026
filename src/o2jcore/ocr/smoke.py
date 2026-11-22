"""Minimal OCR smoke-check primitives.

Deliberately small: ONE synthetic degradation level ("light") and a thin
subprocess wrapper around the `tesseract` binary. No Augraphy, no
engine/noise-level matrix -- see src/o2jcore/ocr/__init__.py.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from o2jcore.text.pdf_text import pdfium_lock

import numpy as np
from PIL import Image, ImageFilter


def degrade_light(img: Image.Image, seed: int = 42) -> Image.Image:
    """Apply one fixed, deterministic "light" degradation.

    Pipeline: seeded gaussian blur (radius ~0.6) -> seeded gaussian pixel
    noise (sigma ~3) -> seeded small rotation (+/- 0.4 degrees) -> a JPEG
    re-encode round-trip at quality 85 (compression artifacts).

    Deterministic for a given (img, seed): uses a numpy Generator seeded
    with `seed`, never the global RNG, so repeated calls with the same
    inputs are byte-identical.
    """
    rng = np.random.default_rng(seed)

    rgb = img.convert("RGB")

    # 1. Gaussian blur (deterministic -- PIL's blur has no randomness).
    blurred = rgb.filter(ImageFilter.GaussianBlur(radius=0.6))

    # 2. Gaussian pixel noise, seeded.
    arr = np.asarray(blurred).astype(np.float32)
    noise = rng.normal(loc=0.0, scale=3.0, size=arr.shape)
    noisy_arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    noisy = Image.fromarray(noisy_arr, mode="RGB")

    # 3. Small seeded rotation.
    angle = float(rng.uniform(-0.4, 0.4))
    rotated = noisy.rotate(
        angle,
        resample=Image.BICUBIC,
        expand=False,
        fillcolor=(255, 255, 255),
    )

    # 4. JPEG re-encode round-trip to introduce compression artifacts.
    buf = io.BytesIO()
    rotated.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    result = Image.open(buf)
    result.load()
    return result.convert("RGB")


def render_page_png(pdf_path: Path, page_number: int, dpi: int = 300) -> Image.Image:
    """Render one 1-indexed page of a PDF to a PIL Image at the given dpi.

    Uses pypdfium2 directly (kept separate from o2jcore.text.pdf_text,
    which only extracts text, not raster images).
    """
    import pypdfium2 as pdfium

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if page_number < 1:
        raise ValueError(f"page_number must be 1-indexed and >= 1, got {page_number}")

    scale = dpi / 72.0
    with pdfium_lock:
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            if page_number > len(pdf):
                raise ValueError(
                    f"page {page_number} out of range for {pdf_path} ({len(pdf)} pages)"
                )
            page = pdf[page_number - 1]
            try:
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
    return pil_image.convert("RGB")


def run_tesseract(
    img: Image.Image,
    lang: str = "pol",
    psm: int = 3,
    tessdata_prefix: str | None = None,
) -> str:
    """Run the `tesseract` CLI binary on `img` and return the recognized text.

    Writes `img` to a temp PNG, invokes `tesseract <png> - -l {lang} --psm
    {psm}` (output to stdout), and returns stdout decoded as text. Raises a
    clear RuntimeError if the `tesseract` binary isn't found or exits
    nonzero -- failures are never swallowed.
    """
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "the 'tesseract' binary was not found on PATH; install it "
            "(e.g. `brew install tesseract`) before calling run_tesseract"
        )

    env = os.environ.copy()
    if tessdata_prefix is not None:
        env["TESSDATA_PREFIX"] = str(tessdata_prefix)

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = Path(tmpdir) / "page.png"
        img.convert("RGB").save(png_path, format="PNG")

        proc = subprocess.run(
            ["tesseract", str(png_path), "-", "-l", lang, "--psm", str(psm)],
            capture_output=True,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"tesseract exited with code {proc.returncode}: "
                f"{proc.stderr.decode('utf-8', errors='replace')}"
            )
        return proc.stdout.decode("utf-8", errors="replace")
