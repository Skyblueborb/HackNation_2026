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


def validate_data_root(path: Path) -> Path:
    """Fail fast with an actionable message when the data root is missing.

    Commands that would otherwise scan zero documents call this before doing
    any work; pure path resolution (`data_root()`) stays non-raising so tests
    can import modules without the dataset installed.
    """
    path = Path(path)
    if not path.is_dir():
        raise FileNotFoundError(
            f"data root not found: {path}. Set O2J_DATA_ROOT to the directory "
            "containing dane/przyklad_* (or fix 'data_root' in configs/paths.yaml)."
        )
    return path


def data_root(*, must_exist: bool = False) -> Path:
    override = os.environ.get("O2J_DATA_ROOT")
    if override:
        path = Path(override).expanduser().resolve()
    else:
        value = _config().get("data_root")
        if value is None:
            raise RuntimeError("data_root is not set in configs/paths.yaml or O2J_DATA_ROOT")
        path = Path(value).expanduser().resolve()
    return validate_data_root(path) if must_exist else path


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
