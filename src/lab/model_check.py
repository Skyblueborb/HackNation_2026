"""Document selection for the `lab model-check` harness.

This module owns where benchmark documents come from. It deliberately does not
run OCR or LLMs; those probes are added by later tasks in the same module.
"""

from __future__ import annotations

import json
import random
import shutil
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jiwer

from lab import paths
from lab.eval.metrics import evaluate_run, write_metrics
from o2jcore.spec.loader import load_all_classes
from o2jcore.text.pdf_text import extract_pages
from ocr_api.pdf_to_json import run_document, write_ocr_text
from ocr_common.ports import OCRDocument, OCRPage

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


def _cases_for_set(set_id: str, dane: Path) -> list[DocumentCase]:
    if set_id.startswith("skany_"):
        _, dir_name, scan_id = set_id.split("_", 2)
        pdf = dane / "skany" / dir_name / scan_id / f"{scan_id}.pdf"
        if not pdf.is_file():
            return []
        return [_case_for_pdf(pdf, dane)]
    cases: list[DocumentCase] = []
    for spec in _specs().values():
        pdf = dane / set_id / f"{spec.pdf_stem}.pdf"
        if pdf.is_file():
            cases.append(_case_for_pdf(pdf, dane))
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
        cases.extend(_cases_for_set(set_id, dane))
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

    if analysis == "llm" and not case.has_text_layer:
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
            f"- {mismatch['set']}/{mismatch['doc']} {mismatch['field']}: "
            f"gold={mismatch['gold']!r} pred={mismatch['pred']!r}"
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
