"""Document selection for the `lab model-check` harness.

This module owns where benchmark documents come from. It deliberately does not
run OCR or LLMs; those probes are added by later tasks in the same module.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab import paths
from lab.eval.metrics import evaluate_run, write_metrics
from o2jcore.spec.loader import load_all_classes
from o2jcore.text.pdf_text import extract_pages
from ocr_api.pdf_to_json import run_document, write_ocr_text
from ocr_common.ports import OCRDocument, OCRPage

logger = logging.getLogger("lab.model_check")


def configure_logging(verbose: bool = False) -> None:
    """Attach a progress handler once and set the requested level."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s model-check %(message)s")
    )
    if not any(getattr(h, "_model_check", False) for h in logger.handlers):
        handler._model_check = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


_SCAN_DIR_TO_CLASS = {
    "odwolania": "odwolanie",
    "pelnomocnictwa": "pelnomocnictwo",
    "potwierdzenia": "potwierdzenie_przelewu",
}


@dataclass(frozen=True)
class DocumentCase:
    set_id: str
    pdf: Path
    gold: Path
    class_id: str
    corpus: str
    has_text_layer: bool


def _specs() -> dict[str, Any]:
    return load_all_classes(paths.configs_root() / "classes")


def discover_sets(data_root: Path, corpus: str) -> list[str]:
    """List set ids for the requested corpus in deterministic order."""
    dane = paths.validate_data_root(data_root) / "dane"
    set_ids: list[str] = []
    if corpus in ("przyklad", "all"):
        set_ids.extend(
            sorted(
                (p.name for p in dane.glob("przyklad_*") if p.is_dir()),
                key=lambda name: int(name.split("_")[1]),
            )
        )
    if corpus in ("skany", "all"):
        for dir_name in sorted(_SCAN_DIR_TO_CLASS):
            scan_root = dane / "skany" / dir_name
            for pdf in sorted(scan_root.glob("*/*.pdf")):
                set_ids.append(f"skany_{dir_name}_{pdf.parent.name}")
    return set_ids


def _case_for_pdf(pdf: Path, dane: Path) -> DocumentCase:
    if not pdf.is_file():
        raise ValueError(f"PDF not found: {pdf}")
    try:
        rel = pdf.resolve().relative_to(dane.resolve())
    except ValueError as exc:
        raise ValueError(f"PDF outside data_root: {pdf}") from exc
    parts = rel.parts
    if parts[0] == "skany":
        if len(parts) != 4 or parts[1] not in _SCAN_DIR_TO_CLASS:
            raise ValueError(f"unrecognised scan path: {pdf}")
        dir_name, scan_id = parts[1], parts[2]
        return DocumentCase(
            set_id=f"skany_{dir_name}_{scan_id}",
            pdf=pdf,
            gold=pdf.with_suffix(".json"),
            class_id=_SCAN_DIR_TO_CLASS[dir_name],
            corpus="skany",
            has_text_layer=False,
        )
    if len(parts) == 2 and parts[0].startswith("przyklad_"):
        for spec in _specs().values():
            if pdf.stem == spec.pdf_stem:
                return DocumentCase(
                    set_id=parts[0],
                    pdf=pdf,
                    gold=dane / parts[0] / f"{spec.gold_stem}.json",
                    class_id=spec.id,
                    corpus="przyklad",
                    has_text_layer=True,
                )
    raise ValueError(f"unrecognised PDF path under data_root: {pdf}")


def _cases_for_set(
    set_id: str, dane: Path, missing: list[str] | None = None
) -> list[DocumentCase]:
    if set_id.startswith("skany_"):
        _, dir_name, scan_id = set_id.split("_", 2)
        pdf = dane / "skany" / dir_name / scan_id / f"{scan_id}.pdf"
        if not pdf.is_file():
            if missing is not None:
                missing.append(set_id)
            return []
        return [_case_for_pdf(pdf, dane)]
    cases: list[DocumentCase] = []
    found = False
    for spec in _specs().values():
        pdf = dane / set_id / f"{spec.pdf_stem}.pdf"
        if pdf.is_file():
            found = True
            cases.append(_case_for_pdf(pdf, dane))
    if not found and missing is not None:
        missing.append(set_id)
    return cases


def select_documents(
    data_root: Path,
    *,
    corpus: str,
    count: int,
    random_sample: bool,
    seed: int,
    sets: list[str] | None,
    pdf_paths: list[Path] | None,
    missing: list[str] | None = None,
) -> list[DocumentCase]:
    """Resolve CLI selection options into concrete document cases."""
    dane = paths.validate_data_root(data_root) / "dane"
    if pdf_paths:
        return [_case_for_pdf(pdf, dane) for pdf in pdf_paths]
    if sets:
        selected = list(sets)
    else:
        pool = discover_sets(data_root, corpus)
        if count > 0 and count < len(pool):
            selected = random.Random(seed).sample(pool, count) if random_sample else pool[:count]
        else:
            selected = pool
    cases: list[DocumentCase] = []
    for set_id in selected:
        cases.extend(_cases_for_set(set_id, dane, missing))
    return cases


def _text_layer(pdf: Path) -> str:
    return "\n\n".join(page.text for page in extract_pages(pdf, "pdfplumber"))


def _normalize(text: str) -> str:
    return " ".join(text.replace("#", "").replace("*", "").split())


def _ocr_proxy(case: DocumentCase, texts: list[str]) -> dict[str, Any]:
    if not case.has_text_layer:
        return {"cer": "N/A", "wer": "N/A"}
    reference = _normalize(_text_layer(case.pdf))
    hypothesis = _normalize("\n\n".join(texts))
    if not reference:
        return {"cer": "N/A", "wer": "N/A"}
    import jiwer

    return {
        "cer": round(float(jiwer.cer(reference, hypothesis)), 4),
        "wer": round(float(jiwer.wer(reference, hypothesis)), 4),
    }


def _write_prediction(case: DocumentCase, combo_dir: Path, prediction: dict[str, Any] | None) -> None:
    if prediction is None:
        return
    path = combo_dir / "predictions" / case.set_id / case.gold.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(prediction, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _llm_result(llm: Any, texts: list[str]) -> dict[str, Any] | None:
    if isinstance(llm, dict) and llm.get("rejected"):
        return {}
    if isinstance(llm, dict) and isinstance(llm.get("data"), dict):
        return llm["data"]
    return {"raw_text": "\n\n".join(texts)}


def run_case(
    case: DocumentCase,
    *,
    ocr_model: str,
    llm_profile: str | None,
    analysis: str,
    combo_dir: Path,
    backend: Any = None,
    processor: Any = None,
) -> dict[str, Any]:
    """Run one document through the requested probe and persist its artifacts."""
    combo_dir = Path(combo_dir)
    ocr_dir = combo_dir / "ocr" / case.set_id
    ocr_dir.mkdir(parents=True, exist_ok=True)
    logger.info("case %s/%s analysis=%s", case.set_id, case.class_id, analysis)

    if analysis == "llm" and not case.has_text_layer:
        logger.info("  N/A: %s has no text layer; skipping LLM probe", case.set_id)
        return {
            "set_id": case.set_id,
            "status": "N/A",
            "reason": "scan has no text layer",
            "timings": {"render": 0.0, "ocr": 0.0, "llm": 0.0, "total": 0.0},
            "texts": [],
            "prediction": None,
            "ocr_proxy": {"cer": "N/A", "wer": "N/A"},
        }

    if analysis == "llm":
        started = time.perf_counter()
        text = _text_layer(case.pdf)
        document = OCRDocument(
            backend="text",
            model=llm_profile or "text",
            pages=(OCRPage(number=1, text=text),),
            filename=case.pdf.name,
        )
        llm = processor.process(document) if processor is not None else None
        elapsed = time.perf_counter() - started
        texts = [text]
        prediction = _llm_result(llm, texts)
        timings = {"render": 0.0, "ocr": 0.0, "llm": elapsed, "total": elapsed}
        write_ocr_text(case.pdf, texts, ocr_dir)
        _write_prediction(case, combo_dir, prediction)
        return {
            "set_id": case.set_id,
            "status": "ok",
            "timings": timings,
            "texts": texts,
            "prediction": prediction,
            "ocr_proxy": {"cer": "N/A", "wer": "N/A"},
        }

    if analysis == "ocr":
        if ocr_model == "text":
            started = time.perf_counter()
            texts = [_text_layer(case.pdf)]
            elapsed = time.perf_counter() - started
            timings = {"render": elapsed, "ocr": 0.0, "llm": 0.0, "total": elapsed}
            prediction = None
        else:
            result, timings, texts = run_document(
                case.pdf.read_bytes(), case.pdf.name, ocr_model,
                backend=backend, processor=None,
            )
            prediction = None
    elif analysis == "e2e":
        if ocr_model == "text":
            started = time.perf_counter()
            texts = [_text_layer(case.pdf)]
            render = time.perf_counter() - started
            document = OCRDocument(
                backend="text",
                model=ocr_model,
                pages=tuple(OCRPage(number=i, text=t) for i, t in enumerate(texts, 1)),
                filename=case.pdf.name,
            )
            llm_started = time.perf_counter()
            llm = processor.process(document) if processor is not None else None
            llm_time = time.perf_counter() - llm_started
            prediction = _llm_result(llm, texts)
            timings = {
                "render": render, "ocr": 0.0, "llm": llm_time,
                "total": render + llm_time,
            }
        else:
            kwargs: dict[str, Any] = {"backend": backend}
            if processor is not None:
                kwargs["processor"] = processor
            result, timings, texts = run_document(
                case.pdf.read_bytes(), case.pdf.name, ocr_model, **kwargs
            )
            prediction = result
    else:
        raise ValueError(f"unknown analysis mode: {analysis}")

    write_ocr_text(case.pdf, texts, ocr_dir)
    _write_prediction(case, combo_dir, prediction)
    return {
        "set_id": case.set_id,
        "status": "ok",
        "timings": timings,
        "texts": texts,
        "prediction": prediction,
        "ocr_proxy": _ocr_proxy(case, texts),
    }


def aggregate_speed(rows: list[dict[str, Any]], stages: list[str]) -> dict[str, Any]:
    """Aggregate per-document stage timings."""
    out: dict[str, Any] = {}
    for stage in stages:
        values = [
            float(row["timings"][stage])
            for row in rows
            if stage in row.get("timings", {})
        ]
        if not values:
            out[stage] = {"mean": 0.0, "median": 0.0, "p95": 0.0, "sum": 0.0}
            continue
        p95 = (
            statistics.quantiles(values, n=20, method="inclusive")[18]
            if len(values) > 1
            else values[0]
        )
        out[stage] = {
            "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "p95": round(float(p95), 4),
            "sum": round(sum(values), 4),
        }
    return out


def score_combo(
    cases: list[DocumentCase],
    combo_dir: Path,
    specs: dict[str, Any],
    selected_set_ids: list[str],
) -> dict[str, Any]:
    """Score one combo with the lab evaluator and write its report."""
    combo_dir = Path(combo_dir)
    score_gold = combo_dir / "score-gold"
    skipped: list[str] = []
    for case in cases:
        if not case.gold.exists():
            skipped.append(case.set_id)
            continue
        target = score_gold / case.set_id / case.gold.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(case.gold, target)

    result = evaluate_run(combo_dir / "predictions", score_gold, specs, set_ids=selected_set_ids)
    write_metrics(result, combo_dir / "metrics.json")

    timings_path = combo_dir / "timings.json"
    rows: list[dict[str, Any]] = []
    if timings_path.exists():
        rows = json.loads(timings_path.read_text(encoding="utf-8"))
    speed = aggregate_speed(rows, ["render", "ocr", "llm", "total"])
    proxy_values = [
        row["ocr_proxy"]["cer"] for row in rows
        if isinstance(row.get("ocr_proxy", {}).get("cer"), (int, float))
    ]
    ocr_proxy = {
        "cer_mean": round(statistics.mean(proxy_values), 4) if proxy_values else "N/A",
        "n": len(proxy_values),
    }

    payload = json.loads((combo_dir / "metrics.json").read_text(encoding="utf-8"))
    overall = payload["overall"]
    summary = {
        "n_files_evaluated": payload["n_files_evaluated"],
        "json_invalid_or_missing": payload["json_invalid_or_missing"],
        "exact_f1_skip": overall["exact"]["f1_skip"],
        "fuzzy_f1_skip": overall["fuzzy"]["f1_skip"],
        "speed": speed,
        "ocr_proxy": ocr_proxy,
        "data_skipped": skipped,
    }
    lines = [
        "# Model-check report",
        "",
        f"Files evaluated: {summary['n_files_evaluated']}",
        f"F1 exact (skip nulls): {summary['exact_f1_skip']:.4f}",
        f"F1 fuzzy (skip nulls): {summary['fuzzy_f1_skip']:.4f}",
        f"Invalid or missing predictions: {summary['json_invalid_or_missing']}",
        f"Data skipped: {', '.join(skipped) or 'none'}",
        f"OCR CER proxy mean: {ocr_proxy['cer_mean']}",
        "",
        "## Speed (seconds)",
        "",
    ]
    for stage, values in speed.items():
        lines.append(
            f"- {stage}: mean={values['mean']} median={values['median']} "
            f"p95={values['p95']} sum={values['sum']}"
        )
    lines.extend(["", "## Worst field mismatches", ""])
    for mismatch in result.mismatches[:5]:
        lines.append(
            f"- {mismatch['file']} {mismatch['field']}: "
            f"gold={mismatch['expected']!r} pred={mismatch['got']!r}"
        )
    (combo_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def write_summary(run_dir: Path, results: list[dict[str, Any]]) -> None:
    """Write the cross-combo comparison files."""
    run_dir = Path(run_dir)
    (run_dir / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Model-check summary",
        "",
        "| Analysis | OCR | LLM | Files | F1 exact | F1 fuzzy | CER | Total mean (s) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        speed = row.get("speed", {}).get("total", {}).get("mean", "N/A")
        lines.append(
            f"| {row['analysis']} | {row['ocr_model']} | {row['llm_profile']} | "
            f"{row['n_files_evaluated']} | {row['exact_f1_skip']:.4f} | "
            f"{row['fuzzy_f1_skip']:.4f} | {row['ocr_proxy']['cer_mean']} | {speed} |"
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def execute_model_check(options: dict[str, Any]) -> Path:
    """Run every requested combo and return the run directory."""
    data_root = Path(options["data_root"])
    missing: list[str] = []
    cases = select_documents(
        data_root,
        corpus=options["corpus"],
        count=options["count"],
        random_sample=options["random"],
        seed=options["seed"],
        sets=options.get("sets"),
        pdf_paths=options.get("pdf_paths"),
        missing=missing,
    )
    if not cases:
        raise ValueError("no documents matched the selection")
    if missing:
        logger.warning("missing PDFs skipped: %s", ", ".join(missing))

    analyses = options["analysis"]
    ocr_models = options["ocr_models"]
    llm_profiles = options["llm_profiles"]
    run_dir = Path(options["out_dir"]) / f"{time.strftime('%Y%m%dT%H%M%S')}-{options['seed']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps(_jsonable(options), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    specs = _specs()
    results: list[dict[str, Any]] = []
    combos: list[tuple[str, str, str | None]] = []
    for analysis_name in analyses:
        ocr_values = ["text"] if analysis_name == "llm" else ocr_models
        llm_values = [None] if analysis_name == "ocr" else list(llm_profiles)
        for ocr_value in ocr_values:
            for llm_value in llm_values:
                combos.append((analysis_name, ocr_value, llm_value))
    logger.info(
        "run dir=%s cases=%d analyses=%s combos=%d",
        run_dir, len(cases), ",".join(analyses), len(combos),
    )
    combo_index = 0

    for analysis in analyses:
        ocr_values = ["text"] if analysis == "llm" else ocr_models
        llm_values: list[str | None] = (
            [None] if analysis == "ocr" else list(llm_profiles)
        )
        for ocr_model in ocr_values:
            for llm_profile in llm_values:
                ocr_tag = "text" if ocr_model == "text" else Path(ocr_model).name
                llm_tag = "none" if llm_profile is None else llm_profile
                combo_dir = run_dir / analysis / ocr_tag / llm_tag
                combo_dir.mkdir(parents=True, exist_ok=True)
                combo_index += 1
                logger.info(
                    "[%d/%d] analysis=%s ocr=%s llm=%s",
                    combo_index, len(combos), analysis, ocr_tag, llm_tag,
                )

                from local_ai.app import MlxBackend
                from ocr_api.llm_processor import get_processor

                backend = None if ocr_model == "text" or analysis == "llm" else MlxBackend(ocr_model)
                processor = None if analysis == "ocr" else get_processor(llm_profile)

                rows: list[dict[str, Any]] = []
                for case in cases:
                    row = run_case(
                        case,
                        ocr_model=ocr_model,
                        llm_profile=llm_profile,
                        analysis=analysis,
                        combo_dir=combo_dir,
                        backend=backend,
                        processor=processor,
                    )
                    timings = row["timings"]
                    logger.info(
                        "  render=%.2fs ocr=%.2fs llm=%.2fs total=%.2fs status=%s",
                        timings["render"], timings["ocr"], timings["llm"],
                        timings["total"], row.get("status"),
                    )
                    if row.get("status") != "N/A":
                        rows.append(
                            {
                                "set_id": row["set_id"],
                                "status": row["status"],
                                "timings": row["timings"],
                                "ocr_proxy": row["ocr_proxy"],
                            }
                        )
                (combo_dir / "timings.json").write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                scored_cases = (
                    [case for case in cases if case.has_text_layer]
                    if analysis == "llm"
                    else cases
                )
                set_ids = sorted({case.set_id for case in scored_cases})
                score = score_combo(scored_cases, combo_dir, specs, set_ids)
                score["data_skipped"] = sorted(
                    set(score["data_skipped"]) | set(missing)
                )
                logger.info(
                    "  scored=%d exact_f1_skip=%.4f fuzzy_f1_skip=%.4f skipped=%d",
                    score["n_files_evaluated"], score["exact_f1_skip"],
                    score["fuzzy_f1_skip"], len(score["data_skipped"]),
                )
                results.append(
                    {
                        "analysis": analysis,
                        "ocr_model": ocr_model,
                        "llm_profile": llm_tag,
                        "combo_dir": str(combo_dir.relative_to(run_dir)),
                        **score,
                    }
                )

    write_summary(run_dir, results)
    logger.info("summary written to %s", run_dir / "summary.md")
    return run_dir
