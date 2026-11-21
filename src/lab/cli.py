"""Typer CLI entry point for the o2j-lab research harness.

All commands are stubs for now (A0 scaffolding step) and raise
NotImplementedError; they will be filled in by later steps of the plan.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from lab import paths
from lab.board import write_leaderboard
from lab.cache import read_cached, write_cache
from lab.manifest import finish_manifest, new_manifest, write_manifest
from lab.split import build_split, format_summary, write_split
from lab.eval.errors import write_errors_md
from lab.eval.metrics import evaluate_run, write_metrics
from o2jcore.spec.loader import load_all_classes
from o2jcore.text.pdf_text import extract_pages

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
def ingest(
    extractor: str = typer.Option(
        "pdfplumber",
        "--extractor",
        help="Text-extraction backend: pdfium, pdfplumber, or pdfplumber_layout.",
    ),
    all_: bool = typer.Option(
        True,
        "--all/--no-all",
        help="Ingest every PDF under <data_root>/dane/przyklad_*/*.pdf (default behavior).",
    ),
    data_root: Path | None = typer.Option(
        None, "--data-root", help="Override the data root (defaults to configs/paths.yaml)."
    ),
    work_root: Path | None = typer.Option(
        None, "--work-root", help="Override the work root (defaults to configs/paths.yaml)."
    ),
) -> None:
    """Ingest PDFs and extract text/layout into the content-addressed cache."""
    if not all_:
        raise typer.BadParameter("--no-all is not supported yet; only --all (the default) is.")

    resolved_data_root = data_root if data_root is not None else paths.data_root()
    resolved_work_root = work_root if work_root is not None else paths.work_root()
    cache_root = resolved_work_root / "cache"

    pdf_paths = sorted((resolved_data_root / "dane").glob("przyklad_*/*.pdf"))

    hits = 0
    misses = 0
    start = time.perf_counter()
    for pdf_path in pdf_paths:
        cached = read_cached(cache_root, pdf_path, extractor)
        if cached is not None:
            hits += 1
            continue
        pages = extract_pages(pdf_path, extractor)
        write_cache(cache_root, pdf_path, extractor, pages)
        misses += 1
    elapsed = time.perf_counter() - start

    typer.echo(f"{hits} hits, {misses} misses, total {hits + misses}")
    typer.echo(f"wall time: {elapsed:.2f}s")


@app.command("eval")
def eval_(
    run: Path = typer.Option(
        ...,
        "--run",
        help=(
            "Path to the prediction run directory, mirroring "
            "<gold_dir>/przyklad_NN/<class>.json. metrics.json and "
            "errors.md are written inside this directory. "
            "SPECIAL CASE: if this path does not exist on disk, OR "
            "--pred-equals-gold is passed, gold is evaluated against "
            "itself (pred_dir := gold_dir) instead of erroring -- this is "
            "how the Phase A identity gate is run without materializing "
            "180 literal copies of gold as a fake run, e.g. "
            "`--run work/runs/_identity` (a directory that is never "
            "created as pred data, only as output)."
        ),
    ),
    data_root: Path | None = typer.Option(
        None, "--data-root", help="Override the data root (defaults to configs/paths.yaml)."
    ),
    split: str = typer.Option(
        "all",
        "--split",
        help=(
            "Which sets to evaluate: 'dev', 'holdout', or 'all' (default). "
            "'dev'/'holdout' read work/splits.json -- run `lab split` first."
        ),
    ),
    pred_equals_gold: bool = typer.Option(
        False,
        "--pred-equals-gold",
        help="Force evaluating gold against itself, even if --run exists on disk.",
    ),
) -> None:
    """Evaluate a pipeline run against gold JSON."""
    if split not in ("dev", "holdout", "all"):
        raise typer.BadParameter("--split must be one of: dev, holdout, all")

    resolved_data_root = data_root if data_root is not None else paths.data_root()
    gold_dir = resolved_data_root / "dane"

    identity_mode = pred_equals_gold or not run.exists()
    pred_dir = gold_dir if identity_mode else run
    if identity_mode:
        typer.echo(
            f"[lab eval] evaluating gold against itself "
            f"({'--pred-equals-gold set' if pred_equals_gold else f'--run {run} not found'})"
        )

    set_ids: list[str] | None = None
    if split != "all":
        splits_path = paths.work_root() / "splits.json"
        if not splits_path.exists():
            raise typer.BadParameter(f"no split found at {splits_path}; run `lab split` first")
        with splits_path.open("r", encoding="utf-8") as f:
            split_data = json.load(f)
        set_ids = split_data[split]

    specs = load_all_classes(paths.configs_root() / "classes")

    experiment = "identity" if identity_mode else run.name
    manifest = new_manifest(
        experiment=experiment,
        split="identity" if identity_mode else split,
        data_root=resolved_data_root,
        work_root=paths.work_root(),
    )

    result = evaluate_run(pred_dir, gold_dir, specs, set_ids=set_ids)

    out_dir = run
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "metrics.json"
    errors_path = out_dir / "errors.md"
    write_metrics(result, metrics_path)
    write_errors_md(result.mismatches, errors_path)

    manifest = finish_manifest(manifest)
    manifest_path = write_manifest(manifest, out_dir)

    typer.echo(f"wrote {metrics_path}")
    typer.echo(f"wrote {errors_path}")
    typer.echo(f"wrote {manifest_path}")
    typer.echo("")
    typer.echo(f"{'mode':<8}{'policy':<10}{'precision':<12}{'recall':<12}{'f1':<12}")
    for mode in ("exact", "fuzzy"):
        for policy in ("skip", "tp", "strict"):
            p, r, f1 = result.overall[mode].precision_recall_f1(policy)
            typer.echo(f"{mode:<8}{policy:<10}{p:<12.4f}{r:<12.4f}{f1:<12.4f}")


@app.command("board")
def board(
    work_root: Path | None = typer.Option(
        None, "--work-root", help="Override the work root (defaults to configs/paths.yaml)."
    ),
) -> None:
    """Refresh and print the leaderboard across all runs under <work_root>/runs/."""
    resolved_work_root = work_root if work_root is not None else paths.work_root()
    runs_root = resolved_work_root / "runs"
    out_path = resolved_work_root / "leaderboard.md"
    write_leaderboard(runs_root, out_path)
    typer.echo(out_path.read_text(encoding="utf-8"))


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
