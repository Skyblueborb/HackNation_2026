"""Tests for lab.board."""

from __future__ import annotations

import json
from pathlib import Path

from lab.board import collect_run_summaries, render_leaderboard_md, write_leaderboard


def _write_metrics(path: Path, f1_exact: float, f1_fuzzy: float, n_files: int = 5) -> None:
    payload = {
        "n_files_evaluated": n_files,
        "invalid_json": 0,
        "retries": 0,
        "missing_pred": 0,
        "overall": {
            "exact": {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "f1_skip": f1_exact},
            "fuzzy": {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "f1_skip": f1_fuzzy},
        },
        "per_class": {},
        "per_field": {},
        "per_file": {},
        "classification": {},
        "reject": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_write_leaderboard_no_runs_dir(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"  # never created
    out_path = tmp_path / "leaderboard.md"

    result = write_leaderboard(runs_root, out_path)

    assert result == out_path
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "no runs" in content.lower()


def test_collect_run_summaries_finds_and_sorts(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    run_a = runs_root / "run_a_with_manifest"
    _write_metrics(run_a / "metrics.json", f1_exact=0.5, f1_fuzzy=0.6)
    manifest = {
        "run_id": "run_a_with_manifest",
        "git_commit": "abc123",
        "experiment": "E1",
        "config_sha256": None,
        "model": {"id": "qwen3-8b"},
        "split": "dev",
        "splits_sha256": None,
        "data_commit": None,
        "python_version": "3.13.0",
        "platform": "macOS",
        "started": "2026-11-21T10:00:00+00:00",
        "finished": "2026-11-21T10:05:00+00:00",
    }
    (run_a / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    run_b = runs_root / "run_b_no_manifest"
    _write_metrics(run_b / "metrics.json", f1_exact=0.9, f1_fuzzy=0.95)

    summaries = collect_run_summaries(runs_root)

    assert len(summaries) == 2
    run_ids = [s["run_id"] for s in summaries]
    assert "run_a_with_manifest" in run_ids
    assert "run_b_no_manifest" in run_ids

    # best first (run_b has higher f1_exact_skip)
    assert summaries[0]["run_id"] == "run_b_no_manifest"
    assert summaries[0]["f1_exact_skip"] == 0.9
    assert summaries[1]["run_id"] == "run_a_with_manifest"
    assert summaries[1]["f1_exact_skip"] == 0.5

    md = render_leaderboard_md(summaries)
    assert "run_a_with_manifest" in md
    assert "run_b_no_manifest" in md
    assert "|" in md


def test_run_missing_manifest_uses_dir_name_fallback(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "some_run_dir"
    _write_metrics(run_dir / "metrics.json", f1_exact=0.3, f1_fuzzy=0.4)

    summaries = collect_run_summaries(runs_root)

    assert len(summaries) == 1
    assert summaries[0]["run_id"] == "some_run_dir"
    assert summaries[0]["experiment"] == "some_run_dir"
    assert summaries[0]["model_id"] == "unknown"


def test_render_leaderboard_md_empty_does_not_crash() -> None:
    md = render_leaderboard_md([])
    assert isinstance(md, str)
    assert "no runs" in md.lower()


def test_json_validity_rate_counts_bad_docs_once(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run"
    payload = {
        "n_files_evaluated": 10,
        "invalid_json": 3,
        "missing_pred": 2,
        "json_invalid_or_missing": 4,
        "overall": {"exact": {"f1_skip": 0.5}, "fuzzy": {"f1_skip": 0.5}},
    }
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = collect_run_summaries(runs_root)[0]

    # Not (10 - 3 - 2) / 10: the two counters overlap on one document.
    assert summary["json_validity_rate"] == 0.6
