"""Typer CLI entry point for the o2j-lab research harness.

All commands are stubs for now (A0 scaffolding step) and raise
NotImplementedError; they will be filled in by later steps of the plan.
"""

from __future__ import annotations

from pathlib import Path

import typer

from lab import paths
from lab.split import build_split, format_summary, write_split
from lab.eval.errors import write_errors_md
from lab.eval.metrics import evaluate_run, write_metrics
from o2jcore.spec.loader import load_all_classes

app = typer.Typer(
    name="lab",
    help="Research harness for Odwolania2json: OCR/LLM/pipeline comparison on UZP data.",
    no_args_is_help=True,
)


@app.command("split")
def split(
    holdout: int = typer.Option(20, "--holdout", help="Number of sets held out."),
    seed: int = typer.Option(42, "--seed", help="Random seed for reproducibility."),
    data_root: Path | None = typer.Option(
        None, "--data-root", help="Override the data root (defaults to configs/paths.yaml)."
    ),
) -> None:
    """Split data into dev/holdout sets (stratified, seeded, by set)."""
    resolved_data_root = data_root if data_root is not None else paths.data_root()
    result = build_split(resolved_data_root, n_holdout=holdout, seed=seed)
    out_path = write_split(result, paths.work_root())
    typer.echo(format_summary(result))
    typer.echo(f"wrote {out_path}")


@app.command("ingest")
def ingest() -> None:
    """Ingest PDFs and extract text/layout."""
    raise NotImplementedError


@app.command("eval")
def eval_() -> None:
    """Evaluate a pipeline run against gold JSON."""
    raise NotImplementedError


@app.command("board")
def board() -> None:
    """Show a leaderboard of runs."""
    raise NotImplementedError


@app.command("ocr-prepare")
def ocr_prepare() -> None:
    """Prepare inputs for OCR comparison."""
    raise NotImplementedError


@app.command("ocr-run")
def ocr_run() -> None:
    """Run an OCR engine over prepared inputs."""
    raise NotImplementedError


@app.command("ocr-eval")
def ocr_eval() -> None:
    """Evaluate OCR output (CER/WER) against reference text."""
    raise NotImplementedError


@app.command("collect")
def collect() -> None:
    """Collect results from multiple runs."""
    raise NotImplementedError


@app.command("plots")
def plots() -> None:
    """Generate plots from collected results."""
    raise NotImplementedError


@app.command("report")
def report() -> None:
    """Generate the final report."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
