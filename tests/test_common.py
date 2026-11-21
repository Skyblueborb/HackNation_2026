import io
import logging

from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends
from PIL import Image

from ocr_common import configure_logging, image_is_blank, render_pages, verify_key
from ocr_common.common import get_api_key
from ocr_api.keygen import generate_key


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def test_configure_logging_uses_debug_when_verbose():
    configure_logging(verbose=True)
    assert logging.getLogger("ocr").level == logging.DEBUG
    configure_logging(verbose=False)
    assert logging.getLogger("ocr").level == logging.INFO


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
