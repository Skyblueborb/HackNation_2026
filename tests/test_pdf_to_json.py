import json
from pathlib import Path

import pytest

import ocr_api.pdf_to_json as tool
from ocr_common.ports import OCRDocument


def test_write_result_uses_pdf_basename(tmp_path):
    out = tool.write_result(tmp_path / "odwolanie.pdf", {"a": 1}, tmp_path / "out")
    assert out.name == "odwolanie.json"
    assert json.loads(out.read_text()) == {"a": 1}


def test_check_servers_fails_clearly_when_llm_down(monkeypatch):
    monkeypatch.setattr(tool, "llm_health", lambda base_url: False)
    with pytest.raises(RuntimeError, match="local-llm"):
        tool.check_servers(Path("/tmp/model.gguf"), "local-llm")


def test_run_document_returns_result_and_timings(monkeypatch):
    class FakeBackend:
        def extract_page(self, image):
            return "  OCR TEXT  "

    class FakeProcessor:
        def process(self, document: OCRDocument):
            assert document.pages[0].text == "OCR TEXT"
            return {"class": "odwolanie", "data": {"ok": True}}

    monkeypatch.setattr(tool, "render_pages", lambda data: [object()])
    monkeypatch.setattr(tool, "_load_backend", lambda: FakeBackend())
    monkeypatch.setattr(tool, "_load_processor", lambda: FakeProcessor())

    result, timings = tool.run_document(b"%PDF", "odwolanie.pdf", "m")
    assert result == {"ok": True}
    assert set(timings) == {"render", "ocr", "llm", "total"}
