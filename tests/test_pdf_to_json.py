import json
import sys
import types
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


def test_doc_class_from_filename():
    assert tool.doc_class_from_filename(Path("odwolanie.pdf")) == "odwolanie"
    assert tool.doc_class_from_filename(Path("pelnomocnictwo.pdf")) == "pelnomocnictwo"
    assert tool.doc_class_from_filename(Path("przelew.pdf")) == "przelew"


def test_run_remote_uses_api_response(monkeypatch, tmp_path):
    pdf = tmp_path / "przelew.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        tool,
        "post_analyze",
        lambda **kw: {"canonical_json": {"ok": True}, "backend": "cuda", "pages": []},
    )
    result, timings = tool.run_remote(pdf, "http://192.168.1.220:8000", "token")
    assert result == {"ok": True}
    assert timings["total"] >= 0


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


class _FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_llm_health_requires_status_200(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        tool.urllib.request,
        "urlopen",
        lambda url, timeout: (seen.update(url=url, timeout=timeout) or _FakeResponse(200)),
    )
    assert tool.llm_health("http://host:8081/v1") is True
    assert seen["url"] == "http://host:8081/health"

    for status in (204, 500):
        monkeypatch.setattr(
            tool.urllib.request, "urlopen", lambda url, timeout, s=status: _FakeResponse(s)
        )
        assert tool.llm_health("http://host:8081/v1") is False


def test_llm_health_timeout_is_configurable(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout):
        seen["timeout"] = timeout
        return _FakeResponse(200)

    monkeypatch.setattr(tool.urllib.request, "urlopen", fake_urlopen)
    assert tool.llm_health("http://host:8081/v1", timeout=1.5) is True
    assert seen["timeout"] == 1.5


def test_post_analyze_timeout_is_configurable(monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    httpx = types.ModuleType("httpx")
    httpx.post = fake_post
    monkeypatch.setitem(sys.modules, "httpx", httpx)

    kwargs = dict(
        base_url="http://host",
        pdf=pdf,
        token=None,
        doc_class="odwolanie",
        client_token="t",
        client_doc_id="d",
    )
    tool.post_analyze(**kwargs)
    assert seen["timeout"] == tool.REMOTE_TIMEOUT

    tool.post_analyze(**kwargs, timeout=12.5)
    assert seen["timeout"] == 12.5
