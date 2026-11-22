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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lab import paths
from lab.eval.flatten import canonicalize_path
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
    logger.propagate = False
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
    gold_stem: str = ""


@dataclass(frozen=True)
class _RejectSpec:
    id: str = "nieznany"
    gold_stem: str = "rejected"
    fields: tuple[Any, ...] = ()


def _specs() -> dict[str, Any]:
    return load_all_classes(paths.configs_root() / "classes")


def _specs_with_reject() -> dict[str, Any]:
    specs = dict(_specs())
    specs["nieznany"] = _RejectSpec()
    return specs


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
    if corpus in ("borbelka", "all"):
        root = paths.validate_data_root(data_root) / "testy-dla-borbelka"
        candidates = [
            f"borbelka_{p.name}"
            for p in root.iterdir()
            if p.is_dir() and any(p.glob("*.pdf"))
        ]

        def order(set_id: str) -> int:
            value = set_id.split("_", 1)[1]
            return int(value) if value.lstrip("-").isdigit() else 10**6

        set_ids.extend(sorted(candidates, key=order))
    return set_ids


def _gold_stem_for_class(class_id: str) -> str:
    return next(spec.gold_stem for spec in _specs().values() if spec.id == class_id)


_GOLD_KEY_TO_CLASS = {
    "OdwolanieKIO": "odwolanie",
    "mocodawca": "pelnomocnictwo",
    "przelew_bankowy": "potwierdzenie_przelewu",
}


def _case_from_sidecar(pdf: Path) -> DocumentCase:
    gold = pdf.with_suffix(".json")
    if not gold.is_file():
        raise ValueError(
            f"PDF outside data_root needs a sidecar gold JSON: {gold}"
        )
    try:
        payload = json.loads(gold.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"sidecar gold is not valid JSON: {gold}") from exc
    if isinstance(payload, (dict, list)) and not payload:
        return DocumentCase(
            set_id=f"local_{pdf.stem}",
            pdf=pdf,
            gold=gold,
            class_id="nieznany",
            corpus="local",
            has_text_layer=any(
                page.text.strip() for page in extract_pages(pdf, "pdfplumber")
            ),
            gold_stem="rejected",
        )
    class_id = next(
        (cid for key, cid in _GOLD_KEY_TO_CLASS.items() if key in payload),
        None,
    )
    if class_id is None:
        raise ValueError(f"cannot infer class from sidecar gold: {gold}")
    gold_stem = next(
        spec.gold_stem for spec in _specs().values() if spec.id == class_id
    )
    has_text = any(page.text.strip() for page in extract_pages(pdf, "pdfplumber"))
    return DocumentCase(
        set_id=f"local_{pdf.stem}",
        pdf=pdf,
        gold=gold,
        class_id=class_id,
        corpus="local",
        has_text_layer=has_text,
        gold_stem=gold_stem,
    )


def _case_for_pdf(pdf: Path, dane: Path) -> DocumentCase:
    if not pdf.is_file():
        raise ValueError(f"PDF not found: {pdf}")
    try:
        rel = pdf.resolve().relative_to(dane.resolve())
    except ValueError:
        return _case_from_sidecar(pdf)
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
            gold_stem=_gold_stem_for_class(_SCAN_DIR_TO_CLASS[dir_name]),
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
                    gold_stem=spec.gold_stem,
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


def _cases_for_borbelka_set(set_id: str, data_root: Path) -> list[DocumentCase]:
    dir_name = set_id.split("_", 1)[1]
    folder = data_root / "testy-dla-borbelka" / dir_name
    return [
        replace(_case_from_sidecar(pdf), set_id=set_id, corpus="borbelka")
        for pdf in sorted(folder.glob("*.pdf"))
    ]


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
        if set_id.startswith("borbelka_"):
            cases.extend(_cases_for_borbelka_set(set_id, data_root))
        else:
            cases.extend(_cases_for_set(set_id, dane, missing))
    return cases


def _text_layer(pdf: Path) -> str:
    return "\n\n".join(page.text for page in extract_pages(pdf, "pdfplumber_layout"))


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
    path = combo_dir / "predictions" / case.set_id / _gold_filename(case)
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


def _gold_filename(case: DocumentCase) -> str:
    return f"{case.gold_stem or case.gold.stem}.json"


def _pretty_json(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return "(empty file)"
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


_FIELD_GROUPS = ("text", "date", "identifier", "number", "other")
_TEXT_NORMALIZERS = {"text", "name"}
_DATE_NORMALIZERS = {"date_iso"}
_IDENTIFIER_NORMALIZERS = {"digits", "nrb26", "bzp", "ted"}
_NUMBER_NORMALIZERS = {"enum_int", "money"}


def _group_for_normalizer(normalizer: str | None) -> str:
    if normalizer in _TEXT_NORMALIZERS:
        return "text"
    if normalizer in _DATE_NORMALIZERS:
        return "date"
    if normalizer in _IDENTIFIER_NORMALIZERS:
        return "identifier"
    if normalizer in _NUMBER_NORMALIZERS:
        return "number"
    return "other"


def group_field_scores(result: Any, specs: dict[str, Any]) -> dict[str, Any]:
    """Score fields by value type; strict values are binary per field."""
    normalizers: dict[str, str] = {}
    for spec in specs.values():
        for field_spec in spec.fields:
            normalizers[canonicalize_path(field_spec.path)] = (
                getattr(field_spec, "normalizer", None) or ""
            )

    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in _FIELD_GROUPS}
    for field_key, counts_map in result.per_field.items():
        normalizer = normalizers.get(field_key, "")
        group = _group_for_normalizer(normalizer)
        exact = counts_map["exact"]
        fuzzy = counts_map["fuzzy"]
        _, _, exact_f1 = exact.precision_recall_f1("skip")
        _, _, fuzzy_f1 = fuzzy.precision_recall_f1("skip")
        binary = 1 if exact.fp == 0 and exact.fn == 0 else 0
        grouped[group].append(
            {
                "field": field_key,
                "normalizer": normalizer,
                "exact_f1_skip": round(float(exact_f1), 4),
                "fuzzy_f1_skip": round(float(fuzzy_f1), 4),
                "binary": binary,
                "tp": exact.tp,
                "tn": exact.tn,
                "fp": exact.fp,
                "fn": exact.fn,
            }
        )

    out: dict[str, Any] = {}
    for name, fields in grouped.items():
        count = len(fields)
        binary_mean = round(sum(f["binary"] for f in fields) / count, 4) if count else 0.0
        exact_mean = (
            round(sum(f["exact_f1_skip"] for f in fields) / count, 4) if count else 0.0
        )
        fuzzy_mean = (
            round(sum(f["fuzzy_f1_skip"] for f in fields) / count, 4) if count else 0.0
        )
        strict = name != "text"
        out[name] = {
            "fields": count,
            "exact_f1_skip": binary_mean if strict else exact_mean,
            "fuzzy_f1_skip": binary_mean if strict else fuzzy_mean,
            "binary_f1": binary_mean,
            "field_scores": {f["field"]: f["binary"] for f in fields},
        }

    strict_fields = [
        field
        for name in ("date", "identifier", "number", "other")
        for field in grouped[name]
    ]
    strict_count = len(strict_fields)
    strict_binary = (
        round(sum(f["binary"] for f in strict_fields) / strict_count, 4)
        if strict_count
        else 0.0
    )
    out["strict"] = {
        "fields": strict_count,
        "exact_f1_skip": strict_binary,
        "fuzzy_f1_skip": strict_binary,
        "binary_f1": strict_binary,
        "field_scores": {},
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
        target = score_gold / case.set_id / _gold_filename(case)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(case.gold, target)

    result = evaluate_run(combo_dir / "predictions", score_gold, specs, set_ids=selected_set_ids)
    write_metrics(result, combo_dir / "metrics.json")
    field_groups = group_field_scores(result, specs)

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
        "field_groups": field_groups,
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
    lines.extend(
        [
            "",
            "## Field groups",
            "",
            "| Group | Fields | Exact F1 | Fuzzy F1 | Binary F1 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name in (*_FIELD_GROUPS, "strict"):
        group = field_groups[name]
        lines.append(
            f"| {name} | {group['fields']} | {group['exact_f1_skip']:.4f} | "
            f"{group['fuzzy_f1_skip']:.4f} | {group['binary_f1']:.4f} |"
        )
        logger.info(
            "  field group %s: fields=%d exact_f1_skip=%.4f binary_f1=%.4f",
            name, group["fields"], group["exact_f1_skip"], group["binary_f1"],
        )
    lines.extend(
        [
            "",
            "Numeric/date/identifier fields score 1 only when the exact verdict is TP or TN;",
            "otherwise they score 0. Their aggregate is the mean of those binary scores.",
            "",
            "## Documents",
            "",
        ]
    )
    details: list[dict[str, Any]] = []
    for case in cases:
        rel = f"{case.set_id}/{_gold_filename(case)}"
        counts = result.per_file.get(rel, {}).get("exact")
        case_mismatches = [m for m in result.mismatches if m["file"] == rel]
        if counts is not None:
            _, _, file_f1 = counts.precision_recall_f1("skip")
            correct = counts.tp + counts.tn
            wrong = counts.fp + counts.fn
        else:
            file_f1, correct, wrong = 0.0, 0, 0
        classification = result.classification.get(rel, "n/a")

        ocr_path = combo_dir / "ocr" / case.set_id / f"{case.pdf.stem}.ocr.txt"
        ocr_text = (
            ocr_path.read_text(encoding="utf-8")
            if ocr_path.exists()
            else "(no OCR artifact for this document)"
        )
        pred_path = combo_dir / "predictions" / case.set_id / _gold_filename(case)
        detail = {
            "file": rel,
            "classification": classification,
            "f1_exact_skip": round(file_f1, 4),
            "correct_fields": correct,
            "wrong_fields": wrong,
            "mismatches": case_mismatches,
            "ocr_text": ocr_text,
            "gold_json": _pretty_json(case.gold),
            "predicted_json": _pretty_json(pred_path),
        }
        details.append(detail)

        lines.extend(
            [
                f"### {rel}",
                "",
                f"Classification: {classification}",
                f"F1 exact (skip nulls): {file_f1:.4f}",
                f"Correct fields: {correct}",
                f"Wrong fields: {wrong}",
                "",
                "#### OCR text",
                "",
                "```text",
                ocr_text.rstrip("\n"),
                "```",
                "",
                "#### Field mismatches",
                "",
            ]
        )
        if case_mismatches:
            for mismatch in case_mismatches:
                lines.append(
                    f"- WRONG {mismatch['field']}: gold={mismatch['expected']!r} "
                    f"pred={mismatch['got']!r} verdict={mismatch['verdict']}"
                )
                logger.info(
                    "MISMATCH %s %s gold=%r pred=%r verdict=%s",
                    rel, mismatch["field"], mismatch["expected"],
                    mismatch["got"], mismatch["verdict"],
                )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "#### GOLD JSON",
                "",
                "```json",
                detail["gold_json"],
                "```",
                "",
                "#### PREDICTED JSON",
                "",
                "```json",
                detail["predicted_json"],
                "```",
                "",
            ]
        )

    (combo_dir / "details.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (combo_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("  report written to %s", combo_dir / "report.md")
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
        "| Analysis | OCR | LLM | Files | F1 exact | F1 fuzzy | Text F1 | Strict binary | CER | Total mean (s) | Report |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in results:
        speed = row.get("speed", {}).get("total", {}).get("mean", "N/A")
        groups = row.get("field_groups", {})
        text_f1 = groups.get("text", {}).get("exact_f1_skip", 0.0)
        strict_f1 = groups.get("strict", {}).get("binary_f1", 0.0)
        report_path = (run_dir / row["combo_dir"] / "report.md").resolve()
        lines.append(
            f"| {row['analysis']} | {row['ocr_model']} | {row['llm_profile']} | "
            f"{row['n_files_evaluated']} | {row['exact_f1_skip']:.4f} | "
            f"{row['fuzzy_f1_skip']:.4f} | {text_f1:.4f} | {strict_f1:.4f} | "
            f"{row['ocr_proxy']['cer_mean']} | {speed} | "
            f"[report.md]({report_path}) |"
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
    run_dir = (
        Path(options["out_dir"]).resolve()
        / f"{time.strftime('%Y%m%dT%H%M%S')}-{options['seed']}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps(_jsonable(options), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    specs = _specs_with_reject()
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
