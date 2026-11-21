"""Tests for lab.manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from lab.manifest import finish_manifest, new_manifest, run_dir_name, write_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_new_manifest_git_commit_matches_ground_truth(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    expected = proc.stdout.strip() if proc.returncode == 0 else None

    m = new_manifest(
        experiment="identity",
        split="identity",
        data_root=tmp_path,
        work_root=tmp_path,
    )

    assert m.git_commit == expected
    assert m.git_commit is not None


def test_new_manifest_config_sha256(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("key: value\n", encoding="utf-8")

    m = new_manifest(
        experiment="E1",
        split="all",
        data_root=tmp_path,
        work_root=tmp_path,
        config_path=config_path,
    )

    expected = hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert m.config_sha256 == expected


def test_new_manifest_no_config_path_is_none(tmp_path: Path) -> None:
    m = new_manifest(experiment="identity", split="identity", data_root=tmp_path, work_root=tmp_path)
    assert m.config_sha256 is None


def test_new_manifest_splits_sha256(tmp_path: Path) -> None:
    splits_path = tmp_path / "splits.json"
    splits_path.write_text('{"dev": [], "holdout": []}', encoding="utf-8")

    m = new_manifest(experiment="identity", split="all", data_root=tmp_path, work_root=tmp_path)

    expected = hashlib.sha256(splits_path.read_bytes()).hexdigest()
    assert m.splits_sha256 == expected


def test_new_manifest_no_splits_file_is_none(tmp_path: Path) -> None:
    m = new_manifest(experiment="identity", split="all", data_root=tmp_path, work_root=tmp_path)
    assert m.splits_sha256 is None


def test_run_dir_name_filesystem_safe() -> None:
    name = run_dir_name("E1_identity")
    assert ":" not in name
    assert "/" not in name
    assert len(Path(name).parts) == 1


def test_run_dir_name_with_model_id() -> None:
    name = run_dir_name("E2", model_id="qwen3-8b")
    assert name.endswith("_E2_qwen3-8b")
    assert ":" not in name


def test_write_manifest_round_trips(tmp_path: Path) -> None:
    m = new_manifest(experiment="identity", split="identity", data_root=tmp_path, work_root=tmp_path)
    m = finish_manifest(m)

    out_path = write_manifest(m, tmp_path / "run_dir")

    assert out_path.exists()
    with out_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["run_id"] == m.run_id
    assert data["git_commit"] == m.git_commit
    assert data["experiment"] == m.experiment
    assert data["config_sha256"] == m.config_sha256
    assert data["model"] == m.model
    assert data["split"] == m.split
    assert data["splits_sha256"] == m.splits_sha256
    assert data["data_commit"] == m.data_commit
    assert data["python_version"] == m.python_version
    assert data["platform"] == m.platform
    assert data["started"] == m.started
    assert data["finished"] == m.finished


def test_finish_manifest_sets_finished_after_started(tmp_path: Path) -> None:
    m = new_manifest(experiment="identity", split="identity", data_root=tmp_path, work_root=tmp_path)
    assert m.finished is None

    finished_m = finish_manifest(m)

    assert finished_m.finished is not None
    started_dt = datetime.fromisoformat(finished_m.started)
    finished_dt = datetime.fromisoformat(finished_m.finished)
    assert finished_dt >= started_dt
