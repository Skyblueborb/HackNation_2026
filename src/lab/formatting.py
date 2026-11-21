"""Shared formatting helpers for markdown reports."""

from __future__ import annotations

from typing import Any


def fmt_float(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return "n/a"
