"""Model arena: ranks completed runs and prints the comparison table used to
choose a model. Ranking is on micro-F1 exact/skip; the other columns are
safety and speed tie-breakers (see AI/PLAN.md section 10).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lab.board import collect_run_summaries
from lab.formatting import fmt_float


def rank_runs(
    runs_root: Path,
    *,
    experiment: str | None = None,
    split: str | None = None,
) -> list[dict[str, Any]]:
    rows = collect_run_summaries(Path(runs_root))
    if experiment is not None:
        rows = [row for row in rows if row.get("experiment") == experiment]
    if split is not None:
        rows = [row for row in rows if row.get("split") == split]
    rows = [row for row in rows if row.get("f1_exact_skip") is not None]
    rows.sort(key=lambda row: row["f1_exact_skip"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def best_run(runs_root: Path, **filters: Any) -> dict[str, Any] | None:
    rows = rank_runs(runs_root, **filters)
    return rows[0] if rows else None


def render_arena_md(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Model arena\n\nNo comparable runs yet.\n"
    lines = [
        "# Model arena",
        "",
        "Primary metric: micro-F1 (exact, null_policy=skip).",
        "",
        "| # | model | experiment | split | f1_exact | f1_fuzzy | json_valid | null_halluc | tok/doc | s/doc |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {rank} | {model} | {experiment} | {split} | {f1_exact} | {f1_fuzzy} | {json_valid} | {null_halluc} | {tok_doc} | {sec_doc} |".format(
                rank=row["rank"],
                model=row.get("model_id", "unknown"),
                experiment=row.get("experiment", "unknown"),
                split=row.get("split", "unknown"),
                f1_exact=fmt_float(row.get("f1_exact_skip")),
                f1_fuzzy=fmt_float(row.get("f1_fuzzy_skip")),
                json_valid=fmt_float(row.get("json_validity_rate")),
                null_halluc=fmt_float(row.get("null_hallucination_rate")),
                tok_doc=fmt_float(row.get("tokens_per_doc")),
                sec_doc=fmt_float(row.get("sec_per_doc")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_arena(runs_root: Path, out_path: Path, **filters: Any) -> Path:
    content = render_arena_md(rank_runs(runs_root, **filters))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return out_path
