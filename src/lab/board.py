"""Leaderboard: collects metrics.json/manifest.json from every run under
`<work_root>/runs/*` into a sorted summary table, rendered as markdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab.formatting import fmt_float


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def collect_run_summaries(runs_root: Path) -> list[dict]:
    """Glob `runs_root/*/metrics.json`. For each, read it plus the sibling
    manifest.json if present. Returns one summary dict per run, sorted by
    f1_exact_skip descending (best first)."""
    runs_root = Path(runs_root)
    summaries: list[dict] = []

    if not runs_root.exists():
        return summaries

    for metrics_path in sorted(runs_root.glob("*/metrics.json")):
        run_dir = metrics_path.parent
        metrics = _read_json(metrics_path)
        if metrics is None:
            continue

        manifest = _read_json(run_dir / "manifest.json")

        if manifest is not None:
            run_id = manifest.get("run_id") or run_dir.name
            experiment = manifest.get("experiment") or run_dir.name
            model_id = (manifest.get("model") or {}).get("id") or "unknown"
            split = manifest.get("split") or "unknown"
            started = manifest.get("started")
            finished = manifest.get("finished")
        else:
            run_id = run_dir.name
            experiment = run_dir.name
            model_id = "unknown"
            split = "unknown"
            started = None
            finished = None

        overall = metrics.get("overall", {}) if isinstance(metrics, dict) else {}
        exact = overall.get("exact", {}) if isinstance(overall, dict) else {}
        fuzzy = overall.get("fuzzy", {}) if isinstance(overall, dict) else {}

        f1_exact_skip = exact.get("f1_skip")
        f1_fuzzy_skip = fuzzy.get("f1_skip")

        n_files = metrics.get("n_files_evaluated") or 0
        invalid = metrics.get("invalid_json") or 0
        missing = metrics.get("missing_pred") or 0
        null_stats = metrics.get("null_stats") or {}
        null_gold = (null_stats.get("predicted_value_gold_null") or 0) + (null_stats.get("both_null") or 0)

        summaries.append(
            {
                "run_id": run_id,
                "experiment": experiment,
                "model_id": model_id,
                "split": split,
                "f1_exact_skip": f1_exact_skip,
                "f1_fuzzy_skip": f1_fuzzy_skip,
                "n_files_evaluated": metrics.get("n_files_evaluated"),
                "json_validity_rate": (n_files - invalid - missing) / n_files if n_files else None,
                "null_hallucination_rate": (
                    (null_stats.get("predicted_value_gold_null") or 0) / null_gold if null_gold else None
                ),
                "tokens_per_doc": (
                    ((metrics.get("prompt_tokens") or 0) + (metrics.get("completion_tokens") or 0)) / n_files
                    if n_files
                    else None
                ),
                "sec_per_doc": (metrics.get("seconds") or 0) / n_files if n_files else None,
                "started": started,
                "finished": finished,
            }
        )

    summaries.sort(
        key=lambda s: (s["f1_exact_skip"] if s["f1_exact_skip"] is not None else -1.0),
        reverse=True,
    )
    return summaries


def render_leaderboard_md(summaries: list[dict]) -> str:
    """Render a markdown leaderboard table. Returns a short 'no runs yet'
    message instead of an empty table when `summaries` is empty."""
    if not summaries:
        return "# Leaderboard\n\nNo runs yet. Run `lab eval --run <dir>` to produce one.\n"

    lines = [
        "# Leaderboard",
        "",
        "| run_id | experiment | model | split | n_files | f1_exact | f1_fuzzy | json_valid | null_halluc | tok/doc | s/doc | started |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            "| {run_id} | {experiment} | {model} | {split} | {n_files} | {f1_exact} | {f1_fuzzy} | {json_valid} | {null_halluc} | {tok_doc} | {sec_doc} | {started} |".format(
                run_id=s.get("run_id", "unknown"),
                experiment=s.get("experiment", "unknown"),
                model=s.get("model_id", "unknown"),
                split=s.get("split", "unknown"),
                n_files=s.get("n_files_evaluated") if s.get("n_files_evaluated") is not None else "n/a",
                f1_exact=fmt_float(s.get("f1_exact_skip")),
                f1_fuzzy=fmt_float(s.get("f1_fuzzy_skip")),
                json_valid=fmt_float(s.get("json_validity_rate")),
                null_halluc=fmt_float(s.get("null_hallucination_rate")),
                tok_doc=fmt_float(s.get("tokens_per_doc")),
                sec_doc=fmt_float(s.get("sec_per_doc")),
                started=s.get("started") or "n/a",
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_leaderboard(runs_root: Path, out_path: Path) -> Path:
    """collect_run_summaries then render_leaderboard_md then write to
    `out_path` (parents created as needed). Returns `out_path`."""
    summaries = collect_run_summaries(runs_root)
    content = render_leaderboard_md(summaries)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(content)
    return out_path
