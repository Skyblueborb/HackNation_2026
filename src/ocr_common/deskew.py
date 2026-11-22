"""Tesseract OSD-based image rotation correction.

Uses pytesseract's orientation detection (OSD) to detect and correct
rotations in multiples of 90°. Falls back gracefully if Tesseract is
unavailable or OSD fails (e.g. blank/low-text pages).

Environment variables
---------------------
OCR_DESKEW : "1" (default) | "0"
    Set to "0" to disable rotation correction entirely.
OCR_DESKEW_MIN_CONF : float, default "2.0"
    Minimum OSD orientation confidence required to apply a rotation.
    Lower values rotate more aggressively; raise if you see false positives.
"""

from __future__ import annotations

import logging
import os

from PIL import Image

logger = logging.getLogger("ocr")

DESKEW_ENABLED: bool = os.environ.get("OCR_DESKEW", "1") == "1"
FINE_DESKEW_ENABLED: bool = os.environ.get("OCR_FINE_DESKEW", "1") == "1"
FINE_DESKEW_MIN_ANGLE: float = float(os.environ.get("OCR_FINE_DESKEW_MIN_ANGLE", "0.20"))
FINE_DESKEW_MAX_ANGLE: float = float(os.environ.get("OCR_FINE_DESKEW_MAX_ANGLE", "15.0"))

# Lazily resolved on first call so import is cheap when deskew is disabled.
_tesseract_available: bool | None = None


def _check_tesseract() -> bool:
    """Return True once and cache the result; log a warning on first failure."""
    global _tesseract_available
    if _tesseract_available is None:
        try:
            import pytesseract  # noqa: F401

            # Auto-detect standard Windows install paths if not on PATH
            if os.name == "nt":
                import shutil
                if not shutil.which("tesseract"):
                    standard_paths = [
                        os.environ.get("TESSERACT_CMD"),
                        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
                    ]
                    for path in standard_paths:
                        if path and os.path.isfile(path):
                            pytesseract.pytesseract.tesseract_cmd = path
                            break

            pytesseract.get_tesseract_version()
            _tesseract_available = True
            logger.debug("deskew: Tesseract is available")
        except Exception as exc:
            _tesseract_available = False
            logger.warning(
                "deskew: Tesseract not available (%s) — rotation correction disabled",
                exc,
            )
    return _tesseract_available


def _coarse_deskew(image: Image.Image) -> tuple[Image.Image, int]:
    """Detect and correct coarse rotation in multiples of 90° (0°, 90°, 180°, 270°).

    Returns (rotated_image, applied_angle).
    """
    if not _check_tesseract():
        return image, 0

    try:
        import pytesseract

        thumb = image.copy()
        thumb.thumbnail((900, 900))

        scores: dict[int, int] = {}
        for deg in (0, 180, 90, 270):
            t = thumb.rotate(deg, expand=True) if deg else thumb
            data = pytesseract.image_to_data(t, output_type=pytesseract.Output.DICT)
            words = sum(
                1
                for w, c in zip(data["text"], data["conf"])
                if c != "-1" and float(c) > 50 and len(w.strip()) >= 3
            )
            scores[deg] = words

        s0 = scores[0]
        best_deg = 0

        # Rotate only if another orientation has at least 15 valid words
        # and has at least 2.5x more words than the current 0° orientation.
        for deg in (180, 90, 270):
            if scores[deg] >= 15 and scores[deg] > (s0 * 2.5 + 5):
                if scores[deg] > scores[best_deg]:
                    best_deg = deg

        if best_deg == 0:
            logger.info("deskew: page already upright (words at 0°=%d, scores=%s)", s0, scores)
            return image, 0

        rotated = image.rotate(best_deg, expand=True)
        logger.info(
            "deskew: rotated page by %d° (words: %d at %d° vs %d at 0°)",
            best_deg,
            scores[best_deg],
            best_deg,
            s0,
        )
        return rotated, best_deg

    except Exception as exc:
        logger.debug("deskew: coarse rotation check failed (%s), keeping original", exc)
        return image, 0


def correct_fine_skew(image: Image.Image) -> tuple[Image.Image, float]:
    """Detect and correct fine skew angle (-15° to +15°) using OpenCV text lines.

    Returns (straightened_image, applied_angle_degrees).
    If skew is smaller than FINE_DESKEW_MIN_ANGLE (e.g. < 0.5°), the original image is returned.
    """
    if not FINE_DESKEW_ENABLED:
        return image, 0.0

    try:
        import cv2
        import numpy as np

        img_gray = np.array(image.convert("L"))
        h, w = img_gray.shape
        if max(h, w) > 1200:
            scale = 1200 / max(h, w)
            img_gray = cv2.resize(
                img_gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
            )

        # Threshold to separate text from background
        _, thresh = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

        # Dilate horizontally to connect letters into continuous text lines
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 3))
        dilated = cv2.dilate(thresh, kernel, iterations=1)

        contours, _ = cv2.findContours(dilated, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        angles: list[float] = []
        weights: list[float] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 50:
                continue

            rect = cv2.minAreaRect(cnt)
            (cx, cy), (rw, rh), angle = rect

            length = max(rw, rh)
            thickness = min(rw, rh) + 1e-5
            aspect = length / thickness

            # Keep distinct horizontal text lines
            if aspect < 2.5:
                continue

            # In OpenCV minAreaRect, align longest dimension to horizontal axis
            if rw < rh:
                angle += 90.0

            while angle > 45.0:
                angle -= 90.0
            while angle < -45.0:
                angle += 90.0

            if -FINE_DESKEW_MAX_ANGLE <= angle <= FINE_DESKEW_MAX_ANGLE:
                angles.append(angle)
                # Weight by length^1.5 so long text lines dominate over short noise blobs
                weights.append(length ** 1.5)

        if not angles:
            return image, 0.0

        # Prefer robust median over lines longer than 80px (immune to pixel grid noise)
        long_angles = [a for a, w in zip(angles, weights) if w > (80.0 ** 1.5)]
        if len(long_angles) >= 3:
            median_angle = float(np.median(long_angles))
        else:
            arr_a = np.array(angles)
            arr_w = np.array(weights)
            idx = np.argsort(arr_a)
            sorted_a = arr_a[idx]
            sorted_w = arr_w[idx]
            cum_w = np.cumsum(sorted_w)
            cutoff = cum_w[-1] / 2.0
            med_idx = int(np.searchsorted(cum_w, cutoff))
            median_angle = float(sorted_a[min(med_idx, len(sorted_a) - 1)])

        # Ignore tiny skews to avoid unnecessary interpolation blurring
        if abs(median_angle) < FINE_DESKEW_MIN_ANGLE:
            logger.debug(
                "deskew: fine skew %.2f° below threshold %.2f°, skipping",
                median_angle,
                FINE_DESKEW_MIN_ANGLE,
            )
            return image, 0.0

        # In OpenCV minAreaRect, positive angle is clockwise.
        # PIL rotate is counter-clockwise, so rotating by median_angle straightens it.
        straightened = image.rotate(
            median_angle,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor="white",
        )
        logger.info("deskew: fine skew corrected by %+.2f°", median_angle)
        return straightened, median_angle

    except Exception as exc:
        logger.debug("deskew: fine skew detection failed (%s), skipping", exc)
        return image, 0.0


def deskew_image(image: Image.Image) -> Image.Image:
    """Return the image rotated to portrait and straightened.

    Two-stage pipeline:
      1. Coarse Orientation (0°, 90°, 180°, 270°) via fast OCR readability scoring.
      2. Fine Deskew (-15° to +15°) via OpenCV text-line angle detection.
    """
    if not DESKEW_ENABLED:
        return image

    # Stage 1: Coarse 90° orientation
    coarse, _ = _coarse_deskew(image)

    # Stage 2: Fine skew angle correction (e.g. 5° tilted scan)
    fine, _ = correct_fine_skew(coarse)

    return fine
