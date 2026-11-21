"""Lazy LLM processor: import safety, startup validation, registry caching."""

from __future__ import annotations

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import ocr_api.llm_processor as adapter
from ocr_common.registry import load_llm_processor

SPEC = "ocr_api.llm_processor:processor"


def _stub_processor_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make construction succeed without real config files or LLM network I/O."""
    monkeypatch.setenv("OCR_LLM_MODEL", "local-llm")
    monkeypatch.setattr(adapter, "load_models", lambda path: {"local-llm": object()})
    monkeypatch.setattr(adapter, "LLMClient", lambda model: "client")
    monkeypatch.setattr(adapter, "PromptSet", lambda: "prompts")
    monkeypatch.setattr(adapter, "load_all_classes", lambda *a: {"odwolanie": "spec"})
    monkeypatch.setattr(adapter, "_processor", None)


def test_invalid_model_does_not_break_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_LLM_MODEL", "definitely-not-a-profile")
    spec = importlib.util.spec_from_file_location(
        "_llm_processor_import_probe", Path(adapter.__file__)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Import only defines names; it never constructs or validates a processor.
    assert module._processor is None


def test_validate_model_lists_available_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adapter,
        "load_models",
        lambda path: {"local-llm": object(), "qwen3-8b": object()},
    )
    with pytest.raises(ValueError) as exc:
        adapter.validate_model("missing-profile")
    message = str(exc.value)
    assert "missing-profile" in message
    assert "local-llm" in message
    assert "qwen3-8b" in message


def test_validate_model_accepts_known_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_LLM_MODEL", "local-llm")
    monkeypatch.setattr(adapter, "load_models", lambda path: {"local-llm": object()})
    assert adapter.validate_model() is None


def test_registry_returns_processor_with_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_processor_build(monkeypatch)
    processor = load_llm_processor(SPEC)
    assert processor is not None
    assert hasattr(processor, "process")


def test_processor_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_processor_build(monkeypatch)
    first = adapter.get_processor()
    second = adapter.get_processor()
    assert first is second
    assert adapter._processor is first


def test_registry_proxy_defers_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_processor", None)
    proxy = load_llm_processor(SPEC)
    assert hasattr(proxy, "process")
    assert adapter._processor is None


def test_proxy_delegates_to_built_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()

    class Fake:
        def process(self, document):
            return sentinel

    monkeypatch.setattr(adapter, "_processor", Fake())
    proxy = load_llm_processor(SPEC)
    assert proxy.process(None) is sentinel


def test_concurrent_get_processor_builds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_processor_build(monkeypatch)
    calls = []
    base = adapter.LabLLMProcessor

    def counting():
        calls.append(1)
        time.sleep(0.02)
        return base()

    monkeypatch.setattr(adapter, "LabLLMProcessor", counting)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: adapter.get_processor(), range(8)))
    assert len(calls) == 1
    assert all(result is results[0] for result in results)
