import io
import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends
from PIL import Image

import ocr_common.common as common
from o2jcore.text import pdf_text
from ocr_common import configure_logging, image_is_blank, render_pages, verify_key
from ocr_common.common import get_api_key
from ocr_api.keygen import generate_key


class _RecordingLock:
    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *args):
        return False


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def test_configure_logging_uses_debug_when_verbose():
    configure_logging(verbose=True)
    assert logging.getLogger("ocr").level == logging.DEBUG
    configure_logging(verbose=False)
    assert logging.getLogger("ocr").level == logging.INFO


def test_pdfium_lock_is_shared_between_modules():
    assert common.pdfium_lock is pdf_text.pdfium_lock


def test_render_pages_holds_shared_pdfium_lock(monkeypatch):
    rec = _RecordingLock()
    monkeypatch.setattr(common, "pdfium_lock", rec)

    class FakePage:
        def get_size(self):
            return (100, 100)

        def render(self, scale):
            return SimpleNamespace(to_pil=lambda: Image.new("RGB", (8, 8)))

    class FakeDoc:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter([FakePage()])

    monkeypatch.setattr(common.pypdfium2, "PdfDocument", lambda data: FakeDoc())
    render_pages(b"%PDF")
    assert rec.entered == 1


def test_pdfium_extract_holds_shared_lock(monkeypatch, tmp_path):
    rec = _RecordingLock()
    monkeypatch.setattr(pdf_text, "pdfium_lock", rec)
    calls = []
    monkeypatch.setattr(
        pdf_text,
        "_extract_pdfium_locked",
        lambda path, pdfium: calls.append(path) or [],
    )
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    pdf_text.extract_pages(pdf, "pdfium")
    assert rec.entered == 1
    assert calls == [pdf]


def test_render_pages_caps_edge():
    pages = render_pages(pdf_bytes())
    assert len(pages) == 1
    assert max(pages[0].size) <= 2048


def test_render_pages_honors_custom_max_edge():
    pages = render_pages(pdf_bytes(), max_edge=128)
    assert len(pages) == 1
    assert max(pages[0].size) <= 128


def test_image_is_blank():
    assert image_is_blank(Image.new("RGB", (8, 8), "white"))
    mixed = Image.new("RGB", (8, 8), "white")
    mixed.putpixel((0, 0), (0, 0, 0))
    assert not image_is_blank(mixed)


def test_generated_key_is_long_and_unique():
    a, b = generate_key(), generate_key()
    assert len(a) >= 32
    assert a != b


def test_verify_key_rejects_wrong_key():
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(verify_key)])
    def x():
        return {"ok": True}

    r = TestClient(app).get("/x", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    r = TestClient(app).get("/x", headers={"X-API-Key": get_api_key()})
    assert r.status_code == 200
