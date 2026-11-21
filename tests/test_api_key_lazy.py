"""API_KEY is resolved per request; standalone apps validate at startup."""

from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import local_ai.app as local_app
import ocr_api.app as cuda_app
from ocr_common import verify_key


def test_import_ocr_common_without_api_key_does_not_raise():
    env = os.environ.copy()
    env.pop("API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "import ocr_common"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_wrong_key_returns_401():
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(verify_key)])
    def x():
        return {"ok": True}

    r = TestClient(app).get("/x", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_verify_key_reads_live_env(monkeypatch):
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(verify_key)])
    def x():
        return {"ok": True}

    monkeypatch.setenv("API_KEY", "rotated-key")
    assert TestClient(app).get("/x", headers={"X-API-Key": "rotated-key"}).status_code == 200
    assert TestClient(app).get("/x", headers={"X-API-Key": "test-key"}).status_code == 401


@pytest.mark.parametrize("module", [cuda_app, local_app])
def test_startup_missing_api_key_raises(monkeypatch, module):
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API_KEY"):
        module.validate_startup()


@pytest.mark.parametrize("module", [cuda_app, local_app])
def test_startup_validates_llm_model_when_configured(monkeypatch, module):
    calls = []
    fake = types.ModuleType("ocr_api.llm_processor")
    fake.validate_model = lambda: calls.append(True)
    monkeypatch.setitem(sys.modules, "ocr_api.llm_processor", fake)
    monkeypatch.setenv("OCR_LLM_PROCESSOR", "ocr_api.llm_processor:processor")
    module.validate_startup()
    assert calls == [True]
