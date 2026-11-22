from types import SimpleNamespace

import ocr_api.llm_processor as adapter
from ocr_common.ports import OCRDocument, OCRPage


def test_lab_llm_processor_uses_coworker_module(monkeypatch):
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {"odwolanie": "spec"})
    monkeypatch.setattr(adapter, "classify_by_rules", lambda text: "odwolanie")
    monkeypatch.setattr(
        adapter,
        "extract_document",
        lambda *a, **kw: SimpleNamespace(
            obj={"x": 1}, error=None, responses=[1], sanitized=0, confidence=None
        ),
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
        "rejected": False,
        "sanitized": 0,
        "confidence": None,
    }


def test_lab_llm_processor_missing_spec_has_full_shape(monkeypatch):
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {})
    monkeypatch.setattr(adapter, "classify_by_rules", lambda text: "odwolanie")

    processor = adapter.LabLLMProcessor("qwen")
    document = OCRDocument("mlx", "m", (OCRPage(1, "text"),), filename="odwolanie.pdf")
    assert processor.process(document) == {
        "class": "odwolanie",
        "data": None,
        "error": "no spec for class odwolanie",
        "llm_calls": 0,
        "rejected": False,
        "sanitized": 0,
        "confidence": None,
    }


def test_lab_llm_processor_rejects_unclassified_document(monkeypatch):
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {"odwolanie": "spec"})
    monkeypatch.setattr(adapter, "classify_by_rules", lambda text: None)

    processor = adapter.LabLLMProcessor("qwen")
    document = OCRDocument(
        "mlx", "m", (OCRPage(1, "text"),), filename="negatywny przyklad.pdf"
    )
    assert processor.process(document) == {
        "class": None,
        "data": None,
        "error": None,
        "llm_calls": 0,
        "rejected": True,
        "sanitized": 0,
        "confidence": None,
    }


def _build_processor(monkeypatch):
    """Build a processor with stubbed construction, real classify_by_rules."""
    monkeypatch.setattr(adapter, "load_models", lambda path: {"qwen": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(
        adapter,
        "load_all_classes",
        lambda *a: {
            cid: "spec"
            for cid in ("odwolanie", "pelnomocnictwo", "potwierdzenie_przelewu")
        },
    )
    return adapter.LabLLMProcessor("qwen")


def _ok_extraction():
    return SimpleNamespace(obj={"x": 1}, error=None, responses=[1], confidence=None, sanitized=0)


def test_routing_ignores_a_contradicting_filename(monkeypatch):
    processor = _build_processor(monkeypatch)
    seen = {}

    def fake_extract(*args, **kwargs):
        seen.update(kwargs)
        return _ok_extraction()

    monkeypatch.setattr(adapter, "extract_document", fake_extract)
    document = OCRDocument(
        "mlx",
        "m",
        (OCRPage(1, "pełnomocnictwo mocodawca pełnomocnik umocowanie"),),
        filename="odwolanie.pdf",
    )
    assert processor.process(document)["class"] == "pelnomocnictwo"
    assert seen["ground_null"] == adapter.GROUND_NULL


def test_ambiguous_text_is_rejected_rather_than_broken_by_the_filename(monkeypatch):
    """With no decisive marker the document is rejected; the name cannot save it.

    "odwolanie przelew" scores one weak marker per class, so neither clears the
    margin. The old tie-breaker would have routed this on the filename alone --
    exactly the crutch the graded task removes.
    """
    processor = _build_processor(monkeypatch)
    monkeypatch.setattr(adapter, "extract_document", lambda *a, **kw: _ok_extraction())
    document = OCRDocument(
        "mlx", "m", (OCRPage(1, "odwolanie przelew"),), filename="przelew.pdf"
    )
    result = processor.process(document)
    assert result["class"] is None
    assert result["rejected"] is True


def test_ground_null_choice_is_deliberate(monkeypatch):
    assert adapter.GROUND_NULL is False
    processor = _build_processor(monkeypatch)
    seen = {}

    def fake_extract(*args, **kwargs):
        seen.update(kwargs)
        return _ok_extraction()

    monkeypatch.setattr(adapter, "extract_document", fake_extract)
    document = OCRDocument("mlx", "m", (OCRPage(1, "odwolanie prezesa kio"),))
    processor.process(document)
    assert seen["ground_null"] is adapter.GROUND_NULL
