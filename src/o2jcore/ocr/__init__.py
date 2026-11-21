"""Minimal OCR smoke-check utilities (Phase B, deliberately small).

This package intentionally does NOT implement the full engine/noise-level
benchmark grid described in AI/PLAN.md section 8A. It provides just enough
to sanity-check that Tesseract + the Polish language pack produce
reasonable text on a handful of rendered pages, at a single ("light")
synthetic degradation level.
"""

from __future__ import annotations
