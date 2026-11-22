import asyncio
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.main as main
import ocr_common


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


@pytest.fixture
def analyze_client(tmp_path, monkeypatch):
    monkeypatch.setenv("O2J_DB_PATH", str(tmp_path / "docs.db"))
    monkeypatch.setenv("O2J_DEV_NO_AUTH", "1")
    # The default OCR backend is "text"; these tests exercise the image path
    # with a fake pipeline, so pin the module value under test.
    monkeypatch.setattr(main, "OCR_BACKEND", "cuda")
    with TestClient(main.app) as client:
        yield client


def test_analyze_uses_client_doc_id(analyze_client, monkeypatch):
    async def fake_pipeline(data, extractor, **kwargs):
        return {
            "backend": kwargs["backend"],
            "pages": [{"page": 1, "text": "ocr"}],
        }

    monkeypatch.setattr(ocr_common, "run_analyze_async", fake_pipeline)
    monkeypatch.setattr(main, "_extractor", lambda: object())

    r = analyze_client.post(
        "/api/analyze",
        data={"client_token": "c1", "doc_class": "odwolanie", "client_doc_id": "file-1"},
        files={"file": ("odwolanie.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    docs = analyze_client.get("/api/documents", params={"client_token": "c1"}).json()
    assert len(docs) == 1
    assert docs[0]["client_doc_id"] == "file-1"


def test_run_remote_ocr_posts_pdf_with_api_key(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "backend": "cuda",
                "pages": [{"page": 1, "text": "hello"}],
                "llm": {"class": "odwolanie", "data": {"ok": True}},
            }

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch.setenv("OCR_SERVICE_URL", "http://l4:8000")
    monkeypatch.setenv("OCR_SERVICE_KEY", "secret")
    monkeypatch.setattr(httpx, "post", fake_post)

    out = asyncio.run(main._run_remote_ocr(b"%PDF", "scan.pdf"))
    assert out["pages"] == [{"page": 1, "text": "hello"}]
    assert captured["url"] == "http://l4:8000/analyze"
    assert captured["headers"]["X-API-Key"] == "secret"
    assert captured["files"]["file"][0] == "scan.pdf"


def test_run_remote_ocr_requires_service_url(monkeypatch):
    monkeypatch.delenv("OCR_SERVICE_URL", raising=False)
    with pytest.raises(RuntimeError, match="OCR_SERVICE_URL"):
        asyncio.run(main._run_remote_ocr(b"%PDF", "scan.pdf"))


def test_analyze_with_remote_backend(analyze_client, monkeypatch):
    monkeypatch.setattr(main, "OCR_BACKEND", "remote")

    async def fake_remote(data, filename):
        return {
            "backend": "cuda",
            "pages": [{"page": 1, "text": "hello"}],
            "llm": {"class": "odwolanie", "data": {"ok": True}},
        }

    monkeypatch.setattr(main, "_run_remote_ocr", fake_remote)
    r = analyze_client.post(
        "/api/analyze",
        data={"client_token": "c1", "doc_class": "odwolanie"},
        files={"file": ("scan.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 200
    assert r.json()["llm"]["data"] == {"ok": True}


def test_analyze_rejects_oversized_upload(analyze_client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 32)
    r = analyze_client.post(
        "/api/analyze",
        data={"client_token": "c1"},
        files={"file": ("big.pdf", pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 413


def test_analyze_rejects_non_pdf_content(analyze_client):
    r = analyze_client.post(
        "/api/analyze",
        data={"client_token": "c1"},
        files={"file": ("notpdf.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 415
