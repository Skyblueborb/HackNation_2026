import io

from fastapi.testclient import TestClient
from PIL import Image

import backend.main as main
import ocr_common


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def test_analyze_uses_client_doc_id(tmp_path, monkeypatch):
    monkeypatch.setenv("O2J_DB_PATH", str(tmp_path / "docs.db"))

    async def fake_pipeline(data, extractor, **kwargs):
        return {
            "backend": kwargs["backend"],
            "pages": [{"page": 1, "text": "ocr"}],
        }

    monkeypatch.setattr(ocr_common, "run_ocr_async", fake_pipeline)
    monkeypatch.setattr(main, "_extractor", lambda: object())

    with TestClient(main.app) as client:
        r = client.post(
            "/api/analyze",
            data={"client_token": "c1", "doc_class": "odwolanie", "client_doc_id": "file-1"},
            files={"file": ("odwolanie.pdf", pdf_bytes(), "application/pdf")},
        )
        assert r.status_code == 200
        docs = client.get("/api/documents", params={"client_token": "c1"}).json()
        assert len(docs) == 1
        assert docs[0]["client_doc_id"] == "file-1"
