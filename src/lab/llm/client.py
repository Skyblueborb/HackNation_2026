"""Thin OpenAI-compatible HTTP client for local llama.cpp servers.

The client keeps raw responses, token counts and latency so every run is
comparable. JSON Schema is passed via `response_format` so the server builds
the constrained-decoding grammar; a server that rejects it is retried once
without the field and the fact is recorded in the response.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from lab.llm.config import ModelConfig

Transport = Callable[..., Any]


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    structured: bool

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return 500 <= exc.code < 600
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if isinstance(status, int):
        return 500 <= status < 600
    if isinstance(exc, (ConnectionError, TimeoutError, OSError, urllib.error.URLError)):
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("connect", "connection", "timeout", "servererror"))


def _attr_or_key(obj: Any, attr: str, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, attr, default)


def unwrap_json(text: str) -> str:
    """Strip markdown fences and return just the outermost JSON object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"no JSON object found in model response: {cleaned[:200]!r}")
    return cleaned[start : end + 1]


class LLMClient:
    def __init__(self, model: ModelConfig, *, transport: Transport | None = None, timeout: float = 900.0) -> None:
        self.model = model
        self.timeout = timeout
        self._transport = transport
        self._client: Any = None

    def _create(self, **kwargs: Any) -> Any:
        if self._transport is not None:
            return self._transport(**kwargs)
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.model.base_url, api_key="sk-local", timeout=self.timeout)
        return self._client.chat.completions.create(**kwargs)

    def call_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        content = user
        if self.model.no_think_suffix:
            content = f"{content}\n{self.model.no_think_suffix}"

        kwargs: dict[str, Any] = {
            "model": self.model.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            **self.model.params,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        structured = schema is not None and self.model.structured_output
        if structured:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": schema},
            }

        started = time.perf_counter()
        try:
            response = self._create(**kwargs)
        except Exception as exc:
            original = exc
            response = None
            # Transient failures are retried for every call. What only the
            # structured path can do is drop response_format and try again.
            if _is_transient_error(exc):
                try:
                    response = self._create(**kwargs)
                except Exception as retry_exc:
                    original = retry_exc
            if response is None and schema is not None:
                kwargs.pop("response_format", None)
                try:
                    response = self._create(**kwargs)
                except Exception:
                    raise original
                structured = False
            if response is None:
                raise original
        elapsed = time.perf_counter() - started

        message = _attr_or_key(response, "choices", "choices", [])[0]
        text = _attr_or_key(_attr_or_key(message, "message", "message"), "content", "content")
        if not isinstance(text, str) or not text.strip():
            raise LLMError("empty response content from model")

        usage = _attr_or_key(response, "usage", "usage")
        prompt_tokens = int(_attr_or_key(usage, "prompt_tokens", "prompt_tokens", 0) or 0)
        completion_tokens = int(_attr_or_key(usage, "completion_tokens", "completion_tokens", 0) or 0)
        return LLMResponse(text, prompt_tokens, completion_tokens, elapsed, structured)

    def health(self) -> dict[str, Any]:
        url = self.model.base_url.rsplit("/v1", 1)[0].rstrip("/") + "/health"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace").strip()
                return {"ok": response.status == 200, "status": response.status, "body": body[:200]}
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "status": None, "body": str(exc)[:200]}

    def probe(self) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        response = self.call_json('Zwróć tylko {"ok": true}.', "test", schema, max_tokens=64)
        try:
            payload = json.loads(unwrap_json(response.text))
            ok = payload.get("ok") is True
        except (LLMError, json.JSONDecodeError):
            ok = False
        return {
            "ok": ok,
            "structured": response.structured,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "seconds": round(response.seconds, 3),
            "preview": response.text.strip()[:80],
        }
