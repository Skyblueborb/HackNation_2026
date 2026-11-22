"""Deskew visual smoke-test.

For every image found in <test_dir>/input/ (tests/test_deskew/input):
  1. Optionally apply a forced test rotation (--angle 90/180/270, default: 0 = as-is).
  2. Run deskew_image() on the image via Tesseract OSD.
  3. Write the final deskewed result to <test_dir>/output/ (tests/test_deskew/output):
       <filename> – deskewed image
  4. Print a summary table with detected angle and confidence.

Usage (from tests/test_deskew/ or project root):
------------------------------------------------
    python test_deskew.py                 # deskew images in input/ as-is
    python test_deskew.py --angle 90      # artificially rotate by 90° first to test
    python test_deskew.py --debug-stages  # also save intermediate _original / _rotated
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# Resolve project root & test directories
# ---------------------------------------------------------------------------
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent.parent
DEFAULT_INPUT = TEST_DIR / "input"
DEFAULT_OUTPUT = TEST_DIR / "output"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_deskew():
    """Import deskew_image with a helpful error when the package isn't on sys.path."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    try:
        from ocr_common.deskew import deskew_image
        return deskew_image
    except ModuleNotFoundError as exc:
        sys.exit(
            f"[error] Cannot import ocr_common: {exc}\n"
            "Run the script via `python tests/test_deskew/test_deskew.py` "
            "or activate the project venv first."
        )


def _force_rotate(image: Image.Image, angle: int) -> Image.Image:
    """Rotate PIL image by *angle* degrees CCW with expansion."""
    if angle == 0:
        return image
    return image.rotate(angle, expand=True)


def _side_by_side(images: list[Image.Image], labels: list[str]) -> Image.Image:
    """Stitch images horizontally with a small label bar under each."""
    from PIL import ImageDraw

    padding = 8
    label_h = 24
    max_h = max(im.height for im in images)
    total_w = sum(im.width for im in images) + padding * (len(images) - 1)
    canvas = Image.new("RGB", (total_w, max_h + label_h), (240, 240, 240))
    draw = ImageDraw.Draw(canvas)

    x = 0
    for im, label in zip(images, labels):
        # centre vertically
        y_off = (max_h - im.height) // 2
        canvas.paste(im, (x, y_off))
        draw.text((x + 4, max_h + 4), label, fill=(60, 60, 60))
        x += im.width + padding

    return canvas


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deskew visual smoke-test")
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help="Directory containing source images (default: tests/test_deskew/input/)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Directory for output images (default: tests/test_deskew/output/)",
    )
    parser.add_argument(
        "--angle", type=int, default=0, choices=[0, 90, 180, 270],
        help="Degrees to artificially rotate each image before deskewing (default: 0 = as-is)",
    )
    parser.add_argument(
        "--tilt", type=float, default=0.0,
        help="Degrees to artificially tilt each image by small angle to test fine deskew (e.g. --tilt 5.0)",
    )
    parser.add_argument(
        "--no-rotate", action="store_true",
        help="Skip the forced rotation step — deskew whatever is in input/ as-is",
    )
    parser.add_argument(
        "--debug-stages", action="store_true",
        help="Also save intermediate images (_original and _rotated)",
    )
    parser.add_argument(
        "--composite", action="store_true",
        help="Also save a single side-by-side composite image per file",
    )
    args = parser.parse_args()

    deskew_image = _load_deskew()

    input_dir: Path = args.input
    output_dir: Path = args.output

    if not input_dir.exists():
        sys.exit(f"[error] Input directory not found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not images:
        sys.exit(
            f"[error] No supported images found in {input_dir}\n"
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    angle = 0 if args.no_rotate else args.angle

    # Header
    col = "{:<10} {:>8} {:<45} {:>8}"
    print()
    print(col.format("file", "forced", "detected / actions", "time(s)"))
    print("-" * 75)

    for path in images:
        t0 = time.perf_counter()

        original = Image.open(path).convert("RGB")
        rotated = original
        if angle != 0:
            rotated = _force_rotate(rotated, angle)
        if args.tilt != 0.0:
            rotated = rotated.rotate(
                args.tilt,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor="white",
            )

        # Monkey-patch logger to capture what deskew detected
        import logging

        detected_msgs: list[str] = []
        _real_info = logging.getLogger("ocr").info

        def _capture(msg, *a, **kw):  # noqa: ANN001
            _real_info(msg, *a, **kw)
            if "deskew:" in msg:
                try:
                    formatted = msg % a
                except Exception:
                    formatted = msg
                detected_msgs.append(formatted.replace("deskew: ", ""))

        logging.getLogger("ocr").info = _capture  # type: ignore[method-assign]
        deskewed = deskew_image(rotated)
        logging.getLogger("ocr").info = _real_info  # type: ignore[method-assign]

        elapsed = time.perf_counter() - t0
        action = " | ".join(detected_msgs) if detected_msgs else "no action"

        # Save deskewed result (with original filename)
        deskewed.save(output_dir / path.name)

        # Optional debug stages
        if args.debug_stages:
            stem = path.stem
            ext = path.suffix
            original.save(output_dir / f"{stem}_original{ext}")
            rotated.save(output_dir / f"{stem}_rotated{ext}")

        # Optional composite
        if args.composite:
            composite = _side_by_side(
                [original, rotated, deskewed],
                ["original", f"forced {angle}°+{args.tilt}°", "deskewed"],
            )
            composite.save(output_dir / f"{path.stem}_composite.png")

        # Row summary
        forced_str = f"{angle}°" if args.tilt == 0.0 else f"{angle}°+{args.tilt:.1f}°"
        print(col.format(path.name[:10], forced_str, action[:45], f"{elapsed:.2f}"))

    print()
    print(f"✓ Processed {len(images)} image(s) → {output_dir}")
    if args.composite:
        print("  Composite images saved alongside individual outputs.")
    print()


if __name__ == "__main__":
    logging_import_guard = True
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("ocr").setLevel(logging.INFO)
    main()
