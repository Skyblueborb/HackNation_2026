"""Load an optional LLM processor without the core code importing it."""

from __future__ import annotations

import importlib
from typing import Any, Callable

from ocr_common.ports import LLMProcessor, OCRDocument


class _CallableProcessor:
    def __init__(self, function: Callable[[OCRDocument], Any]) -> None:
        self._function = function

    def process(self, document: OCRDocument) -> Any:
        return self._function(document)


def load_llm_processor(spec: str | None) -> LLMProcessor | None:
    """Resolve `module.path:attribute` into an object with `.process()`.

    The attribute may be an object exposing `process`, or a plain callable.
    Returns None when no processor is configured.
    """
    if not spec:
        return None
    module_path, separator, attribute = spec.partition(":")
    if not separator or not attribute:
        raise ValueError("OCR_LLM_PROCESSOR must be 'module.path:attribute'")
    obj = getattr(importlib.import_module(module_path), attribute)
    if hasattr(obj, "process"):
        return obj
    if callable(obj):
        return _CallableProcessor(obj)
    raise TypeError("LLM processor must have .process() or be callable")
