"""Run manifest: a small JSON record of provenance for a single `lab`
run (eval, and later train/sweep), written alongside metrics.json /
errors.md in the run directory.

See AI/PLAN.md section 11 for the canonical manifest.json shape. The
`prompts_sha256` / `server` / `params` blocks are populated by real LLM
runs; older eval-only runs leave them empty.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_short_sha(cwd: Path) -> str | None:
    """Return `git rev-parse --short HEAD` run in `cwd`, or None if git is
    unavailable, `cwd` isn't inside a git repo, or there is no commit yet.
    Never raises."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _sha256_bytes(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_git_dir(start: Path) -> Path | None:
    """Look for a `.git` dir at `start` or any parent. Returns the directory
    that contains `.git` (the repo working-tree root), or None."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


@dataclass
class RunManifest:
    run_id: str
    git_commit: str | None
    experiment: str
    config_sha256: str | None
    model: dict[str, Any] = field(default_factory=dict)
    prompts_sha256: dict[str, str] = field(default_factory=dict)
    server: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    split: str = "all"
    splits_sha256: str | None = None
    data_commit: str | None = None
    python_version: str = field(default_factory=lambda: sys.version)
    platform: str = field(default_factory=platform.platform)
    started: str = field(default_factory=_now_iso)
    finished: str | None = None


def run_dir_name(experiment: str, model_id: str | None = None) -> str:
    """`<ISO8601 compact, filesystem-safe>_<experiment>[_<model_id>]`,
    e.g. '2026-11-21T18-05-00_identity' or
    '2026-11-21T18-05-00_E2_qwen3-8b'."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    name = f"{stamp}_{experiment}"
    if model_id:
        name = f"{name}_{model_id}"
    return name


def new_manifest(
    *,
    experiment: str,
    split: str,
    data_root: Path,
    work_root: Path,
    config_path: Path | None = None,
    model: dict | None = None,
    prompts_sha256: dict[str, str] | None = None,
    server: dict | None = None,
    params: dict | None = None,
) -> RunManifest:
    """Build a RunManifest with started=now, finished=None."""
    repo_root = Path(__file__).resolve().parents[2]
    git_commit = _git_short_sha(repo_root)

    data_root = Path(data_root)
    data_repo_dir = _find_git_dir(data_root)
    data_commit = _git_short_sha(data_repo_dir) if data_repo_dir is not None else None

    splits_path = Path(work_root) / "splits.json"
    splits_sha256 = _sha256_bytes(splits_path)

    config_sha256 = _sha256_bytes(Path(config_path)) if config_path is not None else None

    model_dict = dict(model) if model else {}
    model_id = model_dict.get("id") if model_dict else None

    run_id = run_dir_name(experiment, model_id)

    return RunManifest(
        run_id=run_id,
        git_commit=git_commit,
        experiment=experiment,
        config_sha256=config_sha256,
        model=model_dict,
        prompts_sha256=dict(prompts_sha256 or {}),
        server=dict(server or {}),
        params=dict(params or {}),
        split=split,
        splits_sha256=splits_sha256,
        data_commit=data_commit,
        started=_now_iso(),
        finished=None,
    )


def finish_manifest(m: RunManifest) -> RunManifest:
    """Returns a copy of `m` with `finished` set to the current UTC time
    (ISO8601)."""
    return replace(m, finished=_now_iso())


def write_manifest(m: RunManifest, run_dir: Path) -> Path:
    """Writes manifest.json into `run_dir` (creating it if needed). Returns
    the path written."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "manifest.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(m), f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return out_path
