"""Path resolution for the o2j-lab research harness.

Resolves the repo root, loads `configs/paths.yaml`, and allows environment
overrides via `O2J_DATA_ROOT` / `O2J_WORK_ROOT`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# src/lab/paths.py -> src/lab -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _config() -> dict:
    config_path = configs_root() / "paths.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def configs_root() -> Path:
    return REPO_ROOT / "configs"


def data_root() -> Path:
    override = os.environ.get("O2J_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    value = _config().get("data_root")
    if value is None:
        raise RuntimeError("data_root is not set in configs/paths.yaml or O2J_DATA_ROOT")
    return Path(value).expanduser().resolve()


def work_root() -> Path:
    override = os.environ.get("O2J_WORK_ROOT")
    if override:
        path = Path(override).expanduser()
    else:
        value = _config().get("work_root", "work")
        path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()
