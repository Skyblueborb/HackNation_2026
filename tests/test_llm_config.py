"""Tests for lab.llm.config."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from lab import paths
from lab.llm.config import load_experiment, load_models

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_models_reads_all_three_local_servers():
    models = load_models(paths.configs_root() / "models.yaml")

    assert set(models) == {
        "qwen3-4b",
        "qwen3-8b",
        "bielik-11b",
        "qwen3-8b-l4",
        "local-llm",
    }
    assert models["qwen3-8b"].port == 8082
    assert str(models["qwen3-8b"].base_url).endswith("/v1")
    assert models["qwen3-8b"].no_think_suffix == "/no_think"
    assert models["bielik-11b"].no_think_suffix is None
    assert models["qwen3-4b"].params["temperature"] == 0


def test_load_models_fills_default_params():
    models = load_models(paths.configs_root() / "models.yaml")
    assert models["bielik-11b"].params["seed"] == 42
    # bielik-11b overrides max_tokens to 1024 in models.yaml (it is the
    # slowest of the three local models); qwen3-4b has no override and
    # falls back to the shared default.
    assert models["bielik-11b"].params["max_tokens"] == 1024
    assert models["qwen3-4b"].params["max_tokens"] == 2048


def test_model_manifest_dict_carries_provenance():
    models = load_models(paths.configs_root() / "models.yaml")
    payload = models["qwen3-8b"].manifest_dict()
    assert payload["id"] == "qwen3-8b"
    assert payload["license"] == "Apache-2.0"
    assert payload["server_flags"]


def test_load_experiment_E0_defaults():
    exp = load_experiment(REPO_ROOT / "configs/experiments/E0_baseline.yaml")

    assert exp.name == "E0_baseline"
    assert exp.split == "dev"
    assert exp.extractor == "pdfplumber_layout"
    assert exp.trim is True
    assert exp.candidates is False
    assert exp.classify_method == "rules"
    assert exp.retry_on_invalid == 1
    assert exp.ground_null is False


def test_load_experiment_rejects_bad_split(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("split: nonsense\n", encoding="utf-8")
    with pytest.raises(ValueError, match="split"):
        load_experiment(path)


def test_load_experiment_accepts_nested_plan_shape(tmp_path: Path):
    path = tmp_path / "exp.yaml"
    path.write_text(
        "name: E2\n"
        "split: holdout\n"
        "ingest: {extractor: pdfium, trim: false, candidates: true}\n"
        "classify: {method: llm}\n"
        "extract: {retry_on_invalid: 2, fewshot: 1}\n"
        "post: {ground_null: true}\n",
        encoding="utf-8",
    )
    exp = load_experiment(path)
    assert (exp.extractor, exp.trim, exp.candidates) == ("pdfium", False, True)
    assert (exp.classify_method, exp.retry_on_invalid, exp.fewshot) == ("llm", 2, 1)
    assert exp.ground_null is True


def test_experiment_manifest_dict_reflects_cli_overrides():
    exp = load_experiment(REPO_ROOT / "configs/experiments/E0_baseline.yaml")

    overridden = replace(exp, split="holdout", limit=3)
    payload = overridden.manifest_dict()

    assert payload["split"] == "holdout"
    assert payload["limit"] == 3
    # Original stays untouched: overrides are applied as a frozen replace.
    assert exp.manifest_dict()["limit"] is None
