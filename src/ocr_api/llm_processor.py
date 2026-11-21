"""Bridge from OCRDocument to the lab LLM pipeline.

This module contains no LLM logic. It only adapts the existing `lab.llm`
pipeline to the `LLMProcessor` contract in `ocr_common.ports`.
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


class LabLLMProcessor:
    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or os.environ.get("OCR_LLM_MODEL", DEFAULT_MODEL)
        models = load_models(REPO_ROOT / "configs" / "models.yaml")
        if self.model_id not in models:
            raise ValueError(f"unknown OCR_LLM_MODEL: {self.model_id}")
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


# Registry target: OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor
processor = LabLLMProcessor()
