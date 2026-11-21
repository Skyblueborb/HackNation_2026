"""Typer CLI entry point for the o2j-lab research harness.

Phase A commands (split/ingest/eval/board, OCR smoke) plus the LLM phase:
serve, models-check, predict-one, run and sweep.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import typer

from lab import paths
from lab.arena import rank_runs, render_arena_md, write_arena
from lab.board import write_leaderboard
from lab.cache import read_cached, write_cache
from lab.eval.errors import write_errors_md
from lab.eval.metrics import EvalResult, evaluate_run, write_metrics
from lab.llm.client import LLMClient
from lab.llm.config import ExperimentConfig, ModelConfig, load_experiment, load_models
from lab.llm.pipeline import PipelineResult, resolve_set_ids, run_pipeline
from lab.llm.prompts import PromptSet
from lab.llm.server import START_TIMEOUT, ensure_server, health_ok, server_command, stop_server
from lab.manifest import finish_manifest, new_manifest, write_manifest
from lab.ocr_smoke import run_smoke_benchmark
from lab.split import build_split, format_summary, write_split
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


@dataclass
class _RunOutcome:
    pipeline: PipelineResult
    metrics: EvalResult
    run_dir: Path
    experiment: ExperimentConfig
    model: ModelConfig


def _load_experiment_and_model(
    config: Path, model_id: str, split: str | None, limit: int | None
) -> tuple[ExperimentConfig, ModelConfig]:
    experiment = load_experiment(config)
    if split is not None:
        experiment = replace(experiment, split=split)
    if limit is not None:
        experiment = replace(experiment, limit=limit)
    models = load_models(paths.configs_root() / "models.yaml")
    if model_id not in models:
        raise typer.BadParameter(
            f"unknown model {model_id!r}; available: {', '.join(sorted(models))}"
        )
    return experiment, models[model_id]


def _execute_run(
    *,
    config: Path,
    model_id: str,
    split: str | None,
    limit: int | None,
    data_root: Path | None,
    work_root: Path | None,
    manage_server: bool = True,
    server_timeout: float = START_TIMEOUT,
) -> _RunOutcome:
    experiment, model = _load_experiment_and_model(config, model_id, split, limit)
    resolved_data_root = data_root if data_root is not None else paths.data_root()
    resolved_work_root = work_root if work_root is not None else paths.work_root()
    specs = load_all_classes(paths.configs_root() / "classes")
    prompts = PromptSet()

    server_proc = None
    if manage_server:
        if not health_ok(model):
            typer.echo(f"[server] starting {model.id} on port {model.port} ...")
        server_proc = ensure_server(model, resolved_work_root, timeout=server_timeout)
    try:
        pipeline_result = run_pipeline(
            experiment=experiment,
            model=model,
            specs=specs,
            data_root=resolved_data_root,
            work_root=resolved_work_root,
            client=LLMClient(model),
            prompts=prompts,
        )
    finally:
        stop_server(server_proc)

    classifications = json.loads(
        (pipeline_result.run_dir / "classification.json").read_text(encoding="utf-8")
    )
    metrics_result = evaluate_run(
        pipeline_result.run_dir,
        resolved_data_root / "dane",
        specs,
        set_ids=resolve_set_ids(experiment, resolved_data_root, resolved_work_root),
        classification=classifications,
        run_stats={
            "model_id": model.id,
            "n_llm_calls": pipeline_result.llm_calls,
            "prompt_tokens": pipeline_result.prompt_tokens,
            "completion_tokens": pipeline_result.completion_tokens,
            "seconds": pipeline_result.seconds,
            "invalid_json": pipeline_result.invalid_json,
            "retries": pipeline_result.retries,
        },
    )

    write_metrics(metrics_result, pipeline_result.run_dir / "metrics.json")
    write_errors_md(metrics_result.mismatches, pipeline_result.run_dir / "errors.md")
    manifest = new_manifest(
        experiment=experiment.name,
        split=experiment.split,
        data_root=resolved_data_root,
        work_root=resolved_work_root,
        config_path=Path(experiment.source_path) if experiment.source_path else None,
        model=model.manifest_dict(),
        prompts_sha256=prompts.sha256(),
        server=model.server_dict(),
        params=model.params,
    )
    write_manifest(finish_manifest(manifest), pipeline_result.run_dir)

    return _RunOutcome(pipeline_result, metrics_result, pipeline_result.run_dir, experiment, model)


def _print_metrics(result: EvalResult) -> None:
    typer.echo(f"{'mode':<8}{'policy':<10}{'precision':<12}{'recall':<12}{'f1':<12}")
    for mode in ("exact", "fuzzy"):
        for policy in ("skip", "tp", "strict"):
            p, r, f1 = result.overall[mode].precision_recall_f1(policy)
            typer.echo(f"{mode:<8}{policy:<10}{p:<12.4f}{r:<12.4f}{f1:<12.4f}")


@app.command("serve")
def serve(
    model: str = typer.Option(..., "--model", help="Model id from configs/models.yaml."),
    work_root: Path | None = typer.Option(None, "--work-root"),
    server_timeout: float = typer.Option(
        START_TIMEOUT, "--server-timeout", help="Seconds to wait for server/model download."
    ),
) -> None:
    """Start exactly one llama-server in the foreground (Ctrl-C to stop)."""
    models = load_models(paths.configs_root() / "models.yaml")
    if model not in models:
        raise typer.BadParameter(
            f"unknown model {model!r}; available: {', '.join(sorted(models))}"
        )
    selected = models[model]
    resolved_work_root = work_root if work_root is not None else paths.work_root()
    proc = ensure_server(selected, resolved_work_root, timeout=server_timeout)
    if proc is None:
        typer.echo(f"{model} is already running on port {selected.port}")
        return
    typer.echo(f"started: {' '.join(server_command(selected))}")
    typer.echo(f"log: {resolved_work_root / 'servers' / f'{model}.log'}")
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(proc)


@app.command("models-check")
def models_check(
    models: str = typer.Option("", "--models", help="Comma-separated model ids (default: all)."),
    manage_server: bool = typer.Option(
        True, "--manage-server/--no-manage-server", help="Start/stop one server per model."
    ),
    server_timeout: float = typer.Option(
        START_TIMEOUT, "--server-timeout", help="Seconds to wait for server/model download."
    ),
) -> None:
    """Check server health and constrained-output support, one model at a time."""
    model_map = load_models(paths.configs_root() / "models.yaml")
    ids = [item.strip() for item in models.split(",") if item.strip()] or list(model_map)
    typer.echo(f"{'model':<16}{'health':<10}{'structured':<12}{'tokens':<10}{'seconds':<10}{'detail'}")
    for model_id in ids:
        if model_id not in model_map:
            typer.echo(f"{model_id:<16}{'unknown':<10}")
            continue
        model = model_map[model_id]
        server_proc = None
        if manage_server and not health_ok(model):
            typer.echo(f"[server] starting {model.id} on port {model.port} ...")
            server_proc = ensure_server(model, paths.work_root(), timeout=server_timeout)
        try:
            client = LLMClient(model)
            health = client.health()
            try:
                probe = client.probe()
            except Exception as exc:
                probe = {
                    "ok": False,
                    "error": str(exc)[:100],
                    "structured": False,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "seconds": 0.0,
                }
            tokens = probe.get("prompt_tokens", 0) + probe.get("completion_tokens", 0)
            detail = probe.get("error") or probe.get("preview") or health.get("body", "")
            typer.echo(
                f"{model_id:<16}{str(health['ok']):<10}{str(probe.get('structured', False)):<12}"
                f"{tokens:<10}{probe.get('seconds', 0.0):<10.3f}{detail}"
            )
        finally:
            stop_server(server_proc)


@app.command("predict-one")
def predict_one(
    set_id: str = typer.Option(..., "--set", help="Set id, e.g. przyklad_01."),
    class_id: str = typer.Option(..., "--class", help="Document class id from configs/classes/."),
    config: Path = typer.Option(
        Path("configs/experiments/E0_baseline.yaml"), "--config", help="Experiment config."
    ),
    model: str = typer.Option(..., "--model", help="Model id from configs/models.yaml."),
    data_root: Path | None = typer.Option(None, "--data-root"),
    work_root: Path | None = typer.Option(None, "--work-root"),
    manage_server: bool = typer.Option(
        True, "--manage-server/--no-manage-server", help="Start/stop the server automatically."
    ),
    server_timeout: float = typer.Option(
        START_TIMEOUT, "--server-timeout", help="Seconds to wait for server/model download."
    ),
) -> None:
    """Run one document through the full pipeline and print its JSON."""
    experiment, selected_model = _load_experiment_and_model(config, model, None, None)
    specs = load_all_classes(paths.configs_root() / "classes")
    if class_id not in specs:
        raise typer.BadParameter(f"unknown class {class_id!r}; available: {', '.join(sorted(specs))}")
    resolved_data_root = data_root if data_root is not None else paths.data_root()
    resolved_work_root = work_root if work_root is not None else paths.work_root()

    run_dir = resolved_work_root / "runs" / f"_predict_{set_id}_{class_id}_{selected_model.id}"
    server_proc = None
    if manage_server:
        if not health_ok(selected_model):
            typer.echo(f"[server] starting {selected_model.id} on port {selected_model.port} ...")
        server_proc = ensure_server(selected_model, resolved_work_root, timeout=server_timeout)
    try:
        result = run_pipeline(
            experiment=experiment,
            model=selected_model,
            specs={class_id: specs[class_id]},
            data_root=resolved_data_root,
            work_root=resolved_work_root,
            run_dir=run_dir,
            set_ids=[set_id],
            class_ids=[class_id],
            client=LLMClient(selected_model),
            prompts=PromptSet(),
        )
    finally:
        stop_server(server_proc)
    if not result.outcomes:
        raise typer.BadParameter(f"no PDF found for {set_id}/{class_id}")
    pred_path = run_dir / set_id / f"{specs[class_id].gold_stem}.json"
    if pred_path.exists():
        typer.echo(pred_path.read_text(encoding="utf-8"))
    else:
        typer.echo(f"no valid JSON produced; see {run_dir / 'raw'}")
        for line in (run_dir / "usage.json").read_text(encoding="utf-8").splitlines():
            typer.echo(line)


@app.command("run")
def run(
    config: Path = typer.Option(..., "--config", help="Experiment YAML config."),
    model: str = typer.Option(..., "--model", help="Model id from configs/models.yaml."),
    split: str | None = typer.Option(None, "--split", help="Override config split: dev/holdout/all."),
    limit: int | None = typer.Option(None, "--limit", help="Only the first N sets (smoke test)."),
    data_root: Path | None = typer.Option(None, "--data-root"),
    work_root: Path | None = typer.Option(None, "--work-root"),
    manage_server: bool = typer.Option(
        True, "--manage-server/--no-manage-server", help="Start/stop the server automatically."
    ),
    server_timeout: float = typer.Option(
        START_TIMEOUT, "--server-timeout", help="Seconds to wait for server/model download."
    ),
) -> None:
    """Run the full pipeline for one model and write metrics into the run dir."""
    outcome = _execute_run(
        config=config,
        model_id=model,
        split=split,
        limit=limit,
        data_root=data_root,
        work_root=work_root,
        manage_server=manage_server,
        server_timeout=server_timeout,
    )
    typer.echo(f"run: {outcome.run_dir}")
    typer.echo(
        f"files: {outcome.metrics.n_files_evaluated}  calls: {outcome.metrics.n_llm_calls}  "
        f"tokens: {outcome.metrics.prompt_tokens + outcome.metrics.completion_tokens}  "
        f"retries: {outcome.metrics.retries}  seconds: {outcome.metrics.seconds:.1f}"
    )
    _print_metrics(outcome.metrics)


@app.command("sweep")
def sweep(
    config: Path = typer.Option(..., "--config", help="Experiment YAML config."),
    models: str = typer.Option(..., "--models", help="Comma-separated model ids."),
    split: str | None = typer.Option(None, "--split", help="Override config split."),
    limit: int | None = typer.Option(None, "--limit", help="Only the first N sets."),
    data_root: Path | None = typer.Option(None, "--data-root"),
    work_root: Path | None = typer.Option(None, "--work-root"),
    manage_server: bool = typer.Option(
        True, "--manage-server/--no-manage-server", help="Start/stop one server per model."
    ),
    server_timeout: float = typer.Option(
        START_TIMEOUT, "--server-timeout", help="Seconds to wait for server/model download."
    ),
) -> None:
    """Run several models on the same config, one server at a time."""
    resolved_work_root = work_root if work_root is not None else paths.work_root()
    ids = [item.strip() for item in models.split(",") if item.strip()]
    for model_id in ids:
        typer.echo(f"[sweep] {model_id}")
        outcome = _execute_run(
            config=config,
            model_id=model_id,
            split=split,
            limit=limit,
            data_root=data_root,
            work_root=work_root,
            manage_server=manage_server,
            server_timeout=server_timeout,
        )
        typer.echo(f"  {outcome.run_dir}")
    experiment = load_experiment(config)
    rows = rank_runs(resolved_work_root / "runs", experiment=experiment.name)
    typer.echo("")
    typer.echo(render_arena_md(rows))
    write_arena(resolved_work_root / "runs", resolved_work_root / "arena.md", experiment=experiment.name)


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


@app.command("ocr-smoke")
def ocr_smoke(
    pages: int = typer.Option(8, "--pages", help="Number of pages to sample (spread across classes)."),
    seed: int = typer.Option(42, "--seed", help="Random seed for the degradation and set selection."),
    data_root: Path | None = typer.Option(
        None, "--data-root", help="Override the data root (defaults to configs/paths.yaml)."
    ),
    work_root: Path | None = typer.Option(
        None, "--work-root", help="Override the work root (defaults to configs/paths.yaml)."
    ),
    tessdata_prefix: str | None = typer.Option(
        None, "--tessdata-prefix", help="TESSDATA_PREFIX to use for the tesseract subprocess."
    ),
) -> None:
    """Minimal OCR sanity check: one engine (tesseract 'pol'), one noise
    level ('light'), a handful of pages. NOT the full engine/noise-level
    benchmark grid from AI/PLAN.md section 8A -- that is explicitly
    deferred; this is a small, fast sanity check only.
    """
    resolved_data_root = data_root if data_root is not None else paths.data_root()
    resolved_work_root = work_root if work_root is not None else paths.work_root()

    result = run_smoke_benchmark(
        resolved_data_root,
        resolved_work_root,
        n_pages=pages,
        seed=seed,
        tessdata_prefix=tessdata_prefix,
    )

    typer.echo(f"source: {result['source']}  n_pages: {result['n_pages']}")
    typer.echo("")
    typer.echo(f"{'set':<16}{'class':<24}{'page':<6}{'gt_chars':<10}{'cer_clean':<12}{'cer_light':<12}")
    for r in result["results"]:
        typer.echo(
            f"{r['set']:<16}{r['class']:<24}{r['page']:<6}{r['gt_chars']:<10}"
            f"{r['cer_clean']:<12.4f}{r['cer_light']:<12.4f}"
        )
    typer.echo("")
    typer.echo(f"mean_cer_clean: {result['mean_cer_clean']:.4f}")
    typer.echo(f"mean_cer_light: {result['mean_cer_light']:.4f}")


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
