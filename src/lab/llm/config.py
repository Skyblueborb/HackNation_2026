"""Loaders for the two YAML configs that drive an LLM run.

`configs/models.yaml` maps a model id to an HTTP endpoint plus generation
parameters; `configs/experiments/*.yaml` describes one reproducible pipeline
variant (which split, which preprocessing switches, how many retries).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PARAMS: dict[str, Any] = {"temperature": 0.0, "seed": 42, "max_tokens": 2048}
DEFAULT_SERVER_FLAGS = "-c 6144 -ngl 20 --jinja --parallel 1"
_VALID_SPLITS = ("dev", "holdout", "all")
_VALID_CLASSIFIERS = ("rules", "llm", "rules+llm")


@dataclass(frozen=True)
class ModelConfig:
    id: str
    base_url: str
    model: str
    params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    no_think_suffix: str | None = None
    license: str | None = None
    hf_repo: str | None = None
    port: int | None = None
    server_flags: str = DEFAULT_SERVER_FLAGS
    structured_output: bool = True

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "base_url": self.base_url,
            "hf_repo": self.hf_repo,
            "license": self.license,
            "params": dict(self.params),
            "no_think_suffix": self.no_think_suffix,
            "server_flags": self.server_flags,
            "structured_output": self.structured_output,
        }

    def server_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "port": self.port,
            "hf_repo": self.hf_repo,
            "flags": self.server_flags,
            "no_think_suffix": self.no_think_suffix,
        }


def load_models(path: Path) -> dict[str, ModelConfig]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"models config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping of model id -> config")

    out: dict[str, ModelConfig] = {}
    for model_id, item in raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"{path}: config for {model_id!r} must be a mapping")
        port = item.get("port")
        base_url = item.get("base_url") or (f"http://localhost:{port}/v1" if port else None)
        if not base_url:
            raise ValueError(f"{path}: {model_id!r} has neither base_url nor port")
        params = {**DEFAULT_PARAMS, **(item.get("params") or {})}
        out[str(model_id)] = ModelConfig(
            id=str(model_id),
            base_url=str(base_url),
            model=str(item.get("model") or model_id),
            params=params,
            no_think_suffix=item.get("no_think_suffix"),
            license=item.get("license"),
            hf_repo=item.get("hf_repo"),
            port=int(port) if port is not None else None,
            server_flags=str(item.get("server_flags") or DEFAULT_SERVER_FLAGS),
            structured_output=bool(item.get("structured_output", True)),
        )
    return out


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    split: str = "dev"
    extractor: str = "pdfplumber"
    trim: bool = True
    head_chars: int = 8000
    tail_chars: int = 2000
    candidates: bool = False
    classify_method: str = "rules"
    retry_on_invalid: int = 1
    fewshot: int = 0
    ground_null: bool = False
    limit: int | None = None
    source_path: str = ""

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "split": self.split,
            "extractor": self.extractor,
            "trim": self.trim,
            "head_chars": self.head_chars,
            "tail_chars": self.tail_chars,
            "candidates": self.candidates,
            "classify_method": self.classify_method,
            "retry_on_invalid": self.retry_on_invalid,
            "fewshot": self.fewshot,
            "ground_null": self.ground_null,
            "limit": self.limit,
        }


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name) or {}
    if not isinstance(value, dict):
        raise ValueError(f"section {name!r} must be a mapping")
    return value


def load_experiment(path: Path) -> ExperimentConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"experiment config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping")

    ingest = _section(raw, "ingest")
    classify = _section(raw, "classify")
    extract = _section(raw, "extract")
    post = _section(raw, "post")

    split = str(raw.get("split", "dev"))
    if split not in _VALID_SPLITS:
        raise ValueError(f"{path}: split must be one of {_VALID_SPLITS}, got {split!r}")
    method = str(classify.get("method", "rules"))
    if method not in _VALID_CLASSIFIERS:
        raise ValueError(f"{path}: classify.method must be one of {_VALID_CLASSIFIERS}")
    retries = int(extract.get("retry_on_invalid", 1))
    if not 0 <= retries <= 3:
        raise ValueError(f"{path}: extract.retry_on_invalid must be in 0..3")
    fewshot = int(extract.get("fewshot", 0))
    if fewshot < 0:
        raise ValueError(f"{path}: extract.fewshot must be >= 0")
    limit = raw.get("limit", extract.get("limit"))
    if limit is not None and int(limit) < 1:
        raise ValueError(f"{path}: limit must be >= 1")

    return ExperimentConfig(
        name=str(raw.get("name") or path.stem),
        split=split,
        extractor=str(ingest.get("extractor", "pdfplumber")),
        trim=bool(ingest.get("trim", True)),
        head_chars=int(ingest.get("head_chars", 8000)),
        tail_chars=int(ingest.get("tail_chars", 2000)),
        candidates=bool(ingest.get("candidates", False)),
        classify_method=method,
        retry_on_invalid=retries,
        fewshot=fewshot,
        ground_null=bool(post.get("ground_null", False)),
        limit=int(limit) if limit is not None else None,
        source_path=str(path),
    )
