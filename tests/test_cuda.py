import contextlib
import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

import ocr_api.app as app_module
import ocr_api.backends as backends


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def install_fake_cuda(monkeypatch):
    calls = {}

    class FakeIds:
        def __init__(self, values):
            self.values = values

        @property
        def shape(self):
            return (1, len(self.values))

        def __getitem__(self, key):
            return FakeIds(self.values[key])

    class FakeOutput:
        def __init__(self, values):
            self.values = FakeIds(values)

        def __getitem__(self, key):
            return self.values[key[1]]

    class Model:
        def to(self, device):
            calls["device"] = device
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            calls["generate"] = kwargs
            return FakeOutput([1, 2, 3, 4])

    class Processor:
        def apply_chat_template(self, conversation, **kwargs):
            calls["conversation"] = conversation
            calls["template"] = kwargs
            return SimpleNamespace(to=lambda device: {"input_ids": FakeIds([1, 2])})

        def decode(self, ids, skip_special_tokens=True):
            return "  hello  "

    class ModelClass:
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            calls["model"] = (name, kwargs)
            return Model()

    class ProcessorClass:
        @classmethod
        def from_pretrained(cls, name):
            return Processor()

    fake_torch = SimpleNamespace(
        bfloat16="bf16",
        cuda=SimpleNamespace(is_available=lambda: True),
        inference_mode=contextlib.nullcontext,
    )
    monkeypatch.setattr(backends, "torch", fake_torch)
    monkeypatch.setattr(backends, "Qwen3_5ForConditionalGeneration", ModelClass)
    monkeypatch.setattr(backends, "AutoProcessor", ProcessorClass)
    monkeypatch.setattr(backends, "_session", None)
    return calls


def test_cuda_model_id_can_be_overridden(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "lightonai/LightOnOCR-3-0.8B")
    import importlib

    importlib.reload(backends)
    assert backends.MODEL_ID == "lightonai/LightOnOCR-3-0.8B"
    monkeypatch.delenv("OCR_MODEL")
    importlib.reload(backends)


def test_cuda_defaults_to_empty_transcription_prompt():
    assert backends.PROMPT == ""


def test_cuda_uses_bfloat16_and_greedy(monkeypatch):
    calls = install_fake_cuda(monkeypatch)
    result = backends.CudaBackend().extract_page(Image.new("RGB", (8, 8)))
    assert result == "hello"
    assert calls["model"][1]["dtype"] == "bf16"
    assert calls["device"] == "cuda"
    assert calls["template"]["enable_thinking"] is False
    assert len(calls["conversation"][0]["content"]) == 1
    assert calls["conversation"][0]["content"][0]["type"] == "image"
    assert calls["generate"]["do_sample"] is False


def test_cuda_app_delegates_to_pipeline(monkeypatch):
    captured = {}

    async def fake(data, extractor, **kwargs):
        captured.update(kwargs)
        return {"backend": "cuda", "pages": []}

    monkeypatch.setattr(app_module, "run_analyze_async", fake)
    r = TestClient(app_module.app).post(
        "/analyze",
        headers={"X-API-Key": "test-key"},
        files={"file": ("a.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    assert captured["backend"] == "cuda"
    assert "processor" in captured


def test_cuda_api_returns_pages(monkeypatch):
    calls = install_fake_cuda(monkeypatch)
    monkeypatch.setattr(app_module, "get_backend", backends.CudaBackend)
    r = TestClient(app_module.app).post(
        "/analyze",
        headers={"X-API-Key": "test-key"},
        files={"file": ("a.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    assert r.json() == {"backend": "cuda", "pages": [{"page": 1, "text": "hello"}]}


def test_cuda_analyze_rejects_oversized_pdf(monkeypatch):
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 16)
    r = TestClient(app_module.app).post(
        "/analyze",
        headers={"X-API-Key": "test-key"},
        files={"file": ("a.pdf", b"x" * 32, "application/pdf")},
    )
    assert r.status_code == 413
