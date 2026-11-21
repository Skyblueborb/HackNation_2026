"""End-to-end check of the optional LLM processor through the shared pipeline.

The LLM server is never contacted: adapter internals are monkeypatched so the
registry target and `run_ocr_async` are exercised without inference.
"""

import asyncio
import io
import json
from types import SimpleNamespace

from PIL import Image

import ocr_api.llm_processor as adapter
from ocr_common.registry import load_llm_processor
from ocr_common.pipeline import run_ocr_async

SPEC = "ocr_api.llm_processor:processor"


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


class FakeExtractor:
    def extract_page(self, image):
        return "odwolanie"


def test_registry_resolves_adapter_processor():
    processor = load_llm_processor(SPEC)
    assert processor is adapter.processor
    assert hasattr(processor, "process")


def test_pipeline_adds_llm_field_without_calling_server(monkeypatch):
    monkeypatch.setattr(adapter, "classify_by_rules", lambda path, text: "odwolanie")
    monkeypatch.setattr(
        adapter,
        "extract_document",
        lambda *a, **kw: SimpleNamespace(obj={"decyzja": "odwolanie"}, error=None, responses=[1]),
    )

    processor = load_llm_processor(SPEC)
    result = asyncio.run(
        run_ocr_async(
            pdf_bytes(),
            FakeExtractor(),
            backend="mlx",
            model="local-llm",
            processor=processor,
            filename="odwolanie.pdf",
        )
    )

    assert result["llm"] == {
        "class": "odwolanie",
        "data": {"decyzja": "odwolanie"},
        "error": None,
        "llm_calls": 1,
    }
    json.dumps(result["llm"])


def test_pipeline_without_processor_has_no_llm_field():
    result = asyncio.run(
        run_ocr_async(pdf_bytes(), FakeExtractor(), backend="mlx", model="local-llm")
    )
    assert "llm" not in result
