"""CORS and API-token regressions for backend.main."""

from __future__ import annotations

import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import backend.main as main

EVIL_ORIGIN = "https://evil.example"


@pytest.fixture(autouse=True)
def _restore_main(monkeypatch):
    yield
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("O2J_DEV_NO_AUTH", raising=False)
    importlib.reload(main)


def _reload_app(monkeypatch, cors_origins: str):
    monkeypatch.setenv("CORS_ORIGINS", cors_origins)
    importlib.reload(main)
    return main.app


def test_disallowed_origin_is_not_reflected(monkeypatch):
    app = _reload_app(monkeypatch, "http://localhost:3000")
    resp = TestClient(app).get("/api/health", headers={"Origin": EVIL_ORIGIN})

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") is None


def test_empty_cors_origins_does_not_fall_back_to_wildcard(monkeypatch):
    app = _reload_app(monkeypatch, "")
    resp = TestClient(app).get("/api/health", headers={"Origin": EVIL_ORIGIN})

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") is None


def test_allowed_origin_is_reflected(monkeypatch):
    app = _reload_app(monkeypatch, "http://localhost:3000")
    resp = TestClient(app).get(
        "/api/health", headers={"Origin": "http://localhost:3000"}
    )

    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_explicit_wildcard_disables_credentials(monkeypatch):
    app = _reload_app(monkeypatch, "*")
    resp = TestClient(app).get("/api/health", headers={"Origin": EVIL_ORIGIN})

    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("access-control-allow-credentials") is None


def _token_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(main.require_token)])
    def ping() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_x_api_token_correct_and_incorrect(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cr3t")
    client = TestClient(_token_app())

    assert client.get("/ping", headers={"X-API-Token": "s3cr3t"}).status_code == 200
    assert client.get("/ping", headers={"X-API-Token": "wrong"}).status_code == 401
    assert client.get("/ping").status_code == 401


def test_startup_requires_api_token(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("O2J_DEV_NO_AUTH", raising=False)
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        with TestClient(main.app):
            pass


def test_dev_no_auth_flag_allows_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("O2J_DB_PATH", str(tmp_path / "dev.db"))
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setenv("O2J_DEV_NO_AUTH", "1")
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/documents").status_code == 200
