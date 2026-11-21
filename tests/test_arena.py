"""Tests for the model arena ranking."""

from __future__ import annotations

import json
from pathlib import Path

from lab.arena import best_run, rank_runs, render_arena_md, write_arena
from lab.formatting import fmt_float


def _write_run(runs_root: Path, name: str, model: str, f1: float, split: str = "dev") -> None:
    run_dir = runs_root / name
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "n_files_evaluated": 10,
        "invalid_json": 1,
        "missing_pred": 0,
        "null_stats": {"predicted_value_gold_null": 2, "both_null": 8},
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "seconds": 20.0,
        "overall": {"exact": {"f1_skip": f1}, "fuzzy": {"f1_skip": f1 + 0.01}},
    }
    manifest = {
        "run_id": name,
        "experiment": "E0_baseline",
        "model": {"id": model},
        "split": split,
        "started": "2026-11-21T10:00:00+00:00",
        "finished": "2026-11-21T10:05:00+00:00",
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_rank_runs_sorts_by_f1_and_filters(tmp_path: Path):
    runs_root = tmp_path / "runs"
    _write_run(runs_root, "a", "qwen3-4b", 0.70)
    _write_run(runs_root, "b", "qwen3-8b", 0.90)
    _write_run(runs_root, "c", "bielik-11b", 0.80, split="holdout")

    rows = rank_runs(runs_root, experiment="E0_baseline", split="dev")
    assert [row["model_id"] for row in rows] == ["qwen3-8b", "qwen3-4b"]
    assert [row["rank"] for row in rows] == [1, 2]
    assert rows[0]["tokens_per_doc"] == 120.0
    assert rows[0]["json_validity_rate"] == 0.9
    assert best_run(runs_root, split="holdout")["model_id"] == "bielik-11b"


def test_arena_markdown_and_file(tmp_path: Path):
    runs_root = tmp_path / "runs"
    _write_run(runs_root, "a", "qwen3-4b", 0.70)
    rows = rank_runs(runs_root)

    md = render_arena_md(rows)
    assert "qwen3-4b" in md
    assert "micro-F1" in md

    out = write_arena(runs_root, tmp_path / "arena.md")
    assert "qwen3-4b" in out.read_text(encoding="utf-8")


def test_shared_float_formatter():
    assert fmt_float(0.71234) == "0.7123"
    assert fmt_float(None) == "n/a"


def test_render_arena_md_empty_is_safe():
    assert "No comparable runs" in render_arena_md([])
