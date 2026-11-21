import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

import local_ai.app as app_module


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def install_fake_mlx(monkeypatch, seen):
    monkeypatch.setattr(app_module, "_session", None)
    monkeypatch.setattr(app_module, "load", lambda p: (seen.update(model=p), (object(), object()))[1])
    monkeypatch.setattr(app_module, "load_config", lambda p: object())
    monkeypatch.setattr(
        app_module,
        "apply_chat_template",
        lambda proc, cfg, prompt, num_images, **kw: seen.update(prompt=prompt, kw=kw) or "formatted",
    )

    def generate(model, processor, prompt, image=None, **kwargs):
        seen["image"] = image
        return SimpleNamespace(text="  hello  ")

    monkeypatch.setattr(app_module, "generate", generate)


def test_model_id_can_be_overridden_for_one_trial(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "fwgpiyawudk/LightOnOCR-3-0.8B-MLX-8bit")
    import importlib

    importlib.reload(app_module)
    assert app_module.MODEL_ID == "fwgpiyawudk/LightOnOCR-3-0.8B-MLX-8bit"
    importlib.reload(app_module)


def test_local_defaults_to_grounding_prompt():
    assert app_module.PROMPT == "grounding"


def test_local_mlx_extracts_text(monkeypatch):
    seen = {}
    install_fake_mlx(monkeypatch, seen)
    result = app_module.MlxBackend().extract_page(Image.new("RGB", (8, 8)))
    assert result == "hello"
    assert seen["prompt"] == "grounding"
    assert seen["kw"]["enable_thinking"] is False
    assert isinstance(seen["image"][0], Image.Image)


def test_local_app_delegates_to_pipeline(monkeypatch):
    captured = {}

    async def fake(data, extractor, **kwargs):
        captured.update(kwargs)
        return {"backend": "mlx", "pages": []}

    monkeypatch.setattr(app_module, "run_ocr_async", fake)
    r = TestClient(app_module.app).post(
        "/analyze",
        headers={"X-API-Key": "test-key"},
        files={"file": ("a.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    assert captured["backend"] == "mlx"
    assert "processor" in captured


def test_local_api_returns_pages(monkeypatch):
    seen = {}
    install_fake_mlx(monkeypatch, seen)
    monkeypatch.setattr(app_module, "get_backend", app_module.MlxBackend)
    r = TestClient(app_module.app).post(
        "/analyze",
        headers={"X-API-Key": "test-key"},
        files={"file": ("a.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    assert r.json() == {"backend": "mlx", "pages": [{"page": 1, "text": "hello"}]}
