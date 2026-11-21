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
    return SimpleNamespace(obj={"x": 1}, error=None, responses=[1])


def test_routing_uses_text_over_filename(monkeypatch):
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


def test_routing_uses_filename_only_as_tie_breaker(monkeypatch):
    processor = _build_processor(monkeypatch)
    monkeypatch.setattr(adapter, "extract_document", lambda *a, **kw: _ok_extraction())
    document = OCRDocument(
        "mlx", "m", (OCRPage(1, "odwolanie przelew"),), filename="przelew.pdf"
    )
    assert processor.process(document)["class"] == "potwierdzenie_przelewu"


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
