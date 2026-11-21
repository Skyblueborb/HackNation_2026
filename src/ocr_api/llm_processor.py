"""Bridge from OCRDocument to the lab LLM pipeline.

This module contains no LLM logic. It only adapts the existing `lab.llm`
pipeline to the `LLMProcessor` contract in `ocr_common.ports`.

The processor is built lazily: importing this module never loads configs or
validates `OCR_LLM_MODEL`. Config validation happens at app startup through
`validate_model()`; inference setup happens on first use through `get_processor()`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from lab.llm.classify import classify_by_rules
from lab.llm.client import LLMClient
from lab.llm.config import load_models
from lab.llm.pipeline import extract_document
from lab.llm.prompts import PromptSet
from lab.paths import REPO_ROOT
from o2jcore.spec.loader import load_all_classes

from ocr_common.ports import OCRDocument

DEFAULT_MODEL = "qwen3-8b"
MODELS_PATH = REPO_ROOT / "configs" / "models.yaml"


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
        path = Path(document.filename or "document.pdf")
        class_id = classify_by_rules(path, text) or "odwolanie"
        if class_id not in self.specs:
            return {
                "class": class_id,
                "data": None,
                "error": f"no spec for class {class_id}",
                "llm_calls": 0,
            }
        result = extract_document(
            self.client,
            self.prompts,
            self.specs[class_id],
            text,
            retries=1,
            ground_null=False,
        )
        return {
            "class": class_id,
            "data": result.obj,
            "error": result.error,
            "llm_calls": len(result.responses),
        }


_processor: LabLLMProcessor | None = None


def get_processor() -> LabLLMProcessor:
    """Return the shared processor, building it on first access."""
    global _processor
    if _processor is None:
        _processor = LabLLMProcessor()
    return _processor


def __getattr__(name: str) -> Any:
    # Registry target: OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor
    if name == "processor":
        return get_processor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
