"""Bridge from OCRDocument to the lab LLM pipeline.

This module contains no LLM logic. It only adapts the existing `lab.llm`
pipeline to the `LLMProcessor` contract in `ocr_common.ports`.

The processor is built lazily: importing this module never loads configs or
validates `OCR_LLM_MODEL`. Config validation happens at app startup through
`validate_model()`; inference setup happens on first use through `get_processor()`.
The registry target `ocr_api.llm_processor:processor` is a deferred proxy so
resolving it at app import does not build the processor.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from lab.llm.classify import classify_by_rules, has_veto_marker
from lab.llm.client import LLMClient
from lab.llm.config import load_models
from lab.llm.pipeline import extract_document
from lab.llm.prompts import PromptSet
from lab.paths import REPO_ROOT
from o2jcore.spec.loader import load_all_classes

from ocr_common.ports import OCRDocument

DEFAULT_MODEL = "qwen3-8b"
MODELS_PATH = REPO_ROOT / "configs" / "models.yaml"

# Grounding replaces model fields with spans copied from the OCR text. It is off
# by default to keep the model's own output and match the baseline experiment.
# Set OCR_LLM_GROUND_NULL=1 to enable it deliberately.
GROUND_NULL = os.environ.get("OCR_LLM_GROUND_NULL", "0") == "1"

# A neutral stem matches none of classify_by_rules' filename stems, so routing
# is decided by text keywords. The filename is used only to break text ties.
_NEUTRAL_PATH = Path("document.pdf")
_FILENAME_RULES = (
    ("odwol", "odwolanie"),
    ("odwoł", "odwolanie"),
    ("pelnom", "pelnomocnictwo"),
    ("pełnom", "pelnomocnictwo"),
    ("przelew", "potwierdzenie_przelewu"),
    ("platn", "potwierdzenie_przelewu"),
    ("trans", "potwierdzenie_przelewu"),
)


def _resolve_model_id(model_id: str | None) -> str:
    return model_id or os.environ.get("OCR_LLM_MODEL", DEFAULT_MODEL)


def _unknown_model_message(model_id: str, models: dict[str, Any]) -> str:
    available = ", ".join(sorted(models))
    return (
        f"unknown OCR_LLM_MODEL profile: {model_id!r}. "
        f"available profiles: {available}"
    )


def validate_model(model_id: str | None = None) -> None:
    """Fail fast if the configured model id is not in configs/models.yaml.

    Called from app startup lifespans so a bad profile is reported before the
    first analyze request. Raises ValueError naming the unknown profile and
    listing the available keys.
    """
    resolved = _resolve_model_id(model_id)
    models = load_models(MODELS_PATH)
    if resolved not in models:
        raise ValueError(_unknown_model_message(resolved, models))


def classify_document(text: str, filename: str | None) -> str | None:
    """Route by text; fall back to the filename only when text is ambiguous.

    Returns None for a document that matches none of the three known classes,
    so callers reject it instead of force-fitting it into "odwolanie". A veto
    marker in the text is a hard reject: the filename is not consulted, since
    the content already proves the document is foreign to all three classes.
    """
    if has_veto_marker(text):
        return None
    class_id = classify_by_rules(_NEUTRAL_PATH, text)
    if class_id is None and filename:
        stem = Path(filename).stem.lower()
        for needle, candidate in _FILENAME_RULES:
            if needle in stem:
                return candidate
    return class_id


class LabLLMProcessor:
    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = _resolve_model_id(model_id)
        models = load_models(MODELS_PATH)
        if self.model_id not in models:
            raise ValueError(_unknown_model_message(self.model_id, models))
        self.client = LLMClient(models[self.model_id])
        self.prompts = PromptSet()
        self.specs = load_all_classes(
            REPO_ROOT / "configs" / "classes", REPO_ROOT / "configs" / "enums"
        )

    def process(self, document: OCRDocument) -> dict[str, Any]:
        text = "\n\n".join(page.text for page in document.pages)
        class_id = classify_document(text, document.filename)
        if class_id is None:
            # Unrecognized document (e.g. a foreign/negative PDF outside the
            # three known classes): reject rather than force-fit it into
            # "odwolanie". Matches the `lab run` convention of an empty
            # result for anything that doesn't classify.
            return {
                "class": None,
                "data": None,
                "error": None,
                "llm_calls": 0,
                "rejected": True,
            }
        if class_id not in self.specs:
            return {
                "class": class_id,
                "data": None,
                "error": f"no spec for class {class_id}",
                "llm_calls": 0,
                "rejected": False,
            }
        result = extract_document(
            self.client,
            self.prompts,
            self.specs[class_id],
            text,
            retries=1,
            ground_null=GROUND_NULL,
        )
        return {
            "class": class_id,
            "data": result.obj,
            "error": result.error,
            "llm_calls": len(result.responses),
            "rejected": False,
        }


_processor: LabLLMProcessor | None = None
_processor_cache: dict[str, LabLLMProcessor] = {}
_processor_lock = threading.Lock()


def get_processor(model_id: str | None = None) -> LabLLMProcessor:
    """Return a cached processor for the resolved model id."""
    global _processor
    resolved = _resolve_model_id(model_id)
    cached = _processor_cache.get(resolved)
    if cached is not None:
        return cached
    with _processor_lock:
        cached = _processor_cache.get(resolved)
        if cached is None:
            cached = LabLLMProcessor() if model_id is None else LabLLMProcessor(model_id)
            _processor_cache[resolved] = cached
        if resolved == _resolve_model_id(None):
            _processor = cached
    return cached


class _ProcessorProxy:
    """Defer construction until a call or an explicit get_processor() at startup."""

    def process(self, document: OCRDocument) -> Any:
        return get_processor().process(document)


_processor_proxy = _ProcessorProxy()


def __getattr__(name: str) -> Any:
    # Registry target: OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor
    if name == "processor":
        return _processor_proxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
