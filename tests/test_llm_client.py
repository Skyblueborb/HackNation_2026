"""Tests for the OpenAI-compatible client: no network, fake transport only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lab.llm.client import LLMClient, LLMError, unwrap_json
from lab.llm.config import load_models
from lab import paths


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )


def _client(transport) -> LLMClient:
    model = load_models(paths.configs_root() / "models.yaml")["qwen3-8b"]
    return LLMClient(model, transport=transport)


def test_call_json_passes_schema_and_no_think_suffix():
    seen: dict = {}

    def transport(**kwargs):
        seen.update(kwargs)
        return _response('{"ok": true}')

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    response = _client(transport).call_json("system", "user", schema)

    assert seen["response_format"]["json_schema"]["schema"] == schema
    assert seen["messages"][1]["content"].endswith("/no_think")
    assert seen["temperature"] == 0
    assert (response.prompt_tokens, response.completion_tokens, response.total_tokens) == (11, 7, 18)
    assert response.structured is True


def test_call_json_skips_response_format_when_model_disables_it():
    seen: dict = {}

    def transport(**kwargs):
        seen.update(kwargs)
        return _response('{"ok": true}')

    model = load_models(paths.configs_root() / "models.yaml")["bielik-11b"]
    response = LLMClient(model, transport=transport).call_json("s", "u", {"type": "object"})

    assert "response_format" not in seen
    assert response.structured is False


def test_call_json_retries_without_response_format_when_unsupported():
    calls: list[dict] = []

    def transport(**kwargs):
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise RuntimeError("400 response_format not supported by this server")
        return _response("{}")

    response = _client(transport).call_json("s", "u", {"type": "object"})
    assert response.structured is False
    assert len(calls) == 2
    assert "response_format" not in calls[1]


def test_call_json_retries_same_structured_request_on_5xx_status():
    calls: list[dict] = []

    class ServiceUnavailable(RuntimeError):
        status_code = 503

    def transport(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ServiceUnavailable("service temporarily unavailable")
        return _response('{"ok": true}')

    response = _client(transport).call_json("s", "u", {"type": "object"})

    assert response.structured is True
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" in calls[1]


def test_call_json_retries_same_structured_request_on_connection_error():
    calls: list[dict] = []

    def transport(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ConnectionResetError("peer reset the connection")
        return _response("{}")

    response = _client(transport).call_json("s", "u", {"type": "object"})

    assert response.structured is True
    assert len(calls) == 2
    assert "response_format" in calls[1]


def test_call_json_retries_transient_error_without_schema():
    calls: list[dict] = []

    class ServiceUnavailable(RuntimeError):
        status_code = 503

    def transport(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ServiceUnavailable("service temporarily unavailable")
        return _response('{"ok": true}')

    response = _client(transport).call_json("s", "u")

    assert response.structured is False
    assert len(calls) == 2
    assert "response_format" not in calls[0]
    assert "response_format" not in calls[1]


def test_call_json_does_not_retry_non_transient_error_without_schema():
    calls: list[dict] = []

    def transport(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("400 bad request")

    with pytest.raises(RuntimeError, match="bad request"):
        _client(transport).call_json("s", "u")

    assert len(calls) == 1


def test_call_json_raises_on_empty_content():
    def transport(**kwargs):
        return _response("   ")

    with pytest.raises(LLMError, match="empty response"):
        _client(transport).call_json("s", "u")


def test_unwrap_json_strips_markdown_fences():
    raw = '```json\n{"a": 1}\n```'
    assert unwrap_json(raw) == '{"a": 1}'


def test_unwrap_json_rejects_text_without_object():
    with pytest.raises(LLMError):
        unwrap_json("just words")
