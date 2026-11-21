from types import SimpleNamespace

import ocr_api.llm_processor as adapter
from ocr_common.ports import OCRDocument, OCRPage


def test_lab_llm_processor_uses_coworker_module(monkeypatch):
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {"odwolanie": "spec"})
    monkeypatch.setattr(adapter, "classify_by_rules", lambda path, text: "odwolanie")
    monkeypatch.setattr(
        adapter,
        "extract_document",
        lambda *a, **kw: SimpleNamespace(obj={"x": 1}, error=None, responses=[1]),
    )

    processor = adapter.LabLLMProcessor("qwen")
    document = OCRDocument(
        "mlx", "m", (OCRPage(1, "text"),), filename="odwolanie.pdf"
    )
    assert processor.process(document) == {
        "class": "odwolanie",
        "data": {"x": 1},
        "error": None,
        "llm_calls": 1,
    }


def test_lab_llm_processor_missing_spec_has_full_shape(monkeypatch):
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {})
    monkeypatch.setattr(adapter, "classify_by_rules", lambda path, text: "odwolanie")

    processor = adapter.LabLLMProcessor("qwen")
    document = OCRDocument("mlx", "m", (OCRPage(1, "text"),), filename="odwolanie.pdf")
    assert processor.process(document) == {
        "class": "odwolanie",
        "data": None,
        "error": "no spec for class odwolanie",
        "llm_calls": 0,
    }
