"""End-to-end pipeline tests with a fake LLM transport (no HTTP calls).

The fake returns the real gold JSON for whichever document is in the prompt,
so the gate below proves that prompt assembly, constrained-output parsing,
Pydantic normalization, derived-field repair and prediction layout preserve
F1 == 1.0 across all 180 gold files.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab import paths
from lab.cache import read_cached, write_cache
from lab.eval.metrics import evaluate_run
from lab.llm.client import LLMClient
from lab.llm.config import load_experiment, load_models
from lab.llm.pipeline import extract_document, run_pipeline
from lab.llm.prompts import PromptSet
from lab.llm.text_prep import prepare_ocr_text
from o2jcore.spec.loader import load_all_classes
from o2jcore.text.pdf_text import PageText

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = paths.data_root() / "dane"
SPECS = load_all_classes(REPO_ROOT / "configs" / "classes")
MODEL = load_models(paths.configs_root() / "models.yaml")["qwen3-8b"]
EXPERIMENT = load_experiment(REPO_ROOT / "configs/experiments/E0_baseline.yaml")
CACHE_ROOT = paths.work_root() / "cache"


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=120),
    )


def _prompt_text(user: str) -> str:
    start = user.index("<ocr_text>") + len("<ocr_text>")
    end = user.index("</ocr_text>", start)
    return user[start:end].strip("\n")


def _gold_payload(set_id: str, cid: str) -> str:
    path = GOLD_DIR / set_id / f"{SPECS[cid].gold_stem}.json"
    return path.read_text(encoding="utf-8")


def _gold_transport(index: dict[str, tuple[str, str]], calls: list[str]):
    def transport(**kwargs):
        text = _prompt_text(kwargs["messages"][1]["content"])
        set_id, cid = index[text]
        calls.append(cid)
        return _response(_gold_payload(set_id, cid))

    return transport


@pytest.fixture(scope="module")
def index() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for path in sorted(GOLD_DIR.glob("przyklad_*")):
        for cid, spec in SPECS.items():
            pdf = path / f"{spec.pdf_stem}.pdf"
            cached = read_cached(CACHE_ROOT, pdf, "pdfplumber")
            assert cached is not None, f"missing cache for {pdf}; run `lab ingest` first"
            text = prepare_ocr_text(cached["pages"])
            assert text not in result
            result[text] = (path.name, cid)
    return result


def test_fake_llm_pipeline_preserves_f1_one_on_all_180_files(tmp_path: Path, index):
    calls: list[str] = []
    result = run_pipeline(
        experiment=EXPERIMENT,
        model=MODEL,
        specs=SPECS,
        data_root=paths.data_root(),
        work_root=paths.work_root(),
        run_dir=tmp_path / "run",
        set_ids=sorted({set_id for set_id, _ in index.values()}),
        client=LLMClient(MODEL, transport=_gold_transport(index, calls)),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 180
    assert all(outcome.ok for outcome in result.outcomes)
    assert len(calls) == 180

    classifications = json.loads((result.run_dir / "classification.json").read_text(encoding="utf-8"))
    metrics = evaluate_run(
        result.run_dir,
        GOLD_DIR,
        SPECS,
        classification=classifications,
        run_stats={
            "model_id": MODEL.id,
            "invalid_json": result.invalid_json,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "seconds": result.seconds,
            "retries": result.retries,
            "n_llm_calls": result.llm_calls,
        },
    )
    assert metrics.n_files_evaluated == 180
    assert metrics.overall["exact"].precision_recall_f1("skip")[2] == pytest.approx(1.0)
    assert metrics.null_stats["predicted_value_gold_null"] == 0
    assert metrics.prompt_tokens == 180 * 500


def _fake_pdf_with_cached_text(
    tmp_path: Path, set_id: str, pdf_stem: str, pages: list[dict]
) -> tuple[Path, Path, Path]:
    data_root = tmp_path / "data"
    work_root = tmp_path / "work"
    pdf = data_root / "dane" / set_id / f"{pdf_stem}.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    write_cache(work_root / "cache", pdf, "pdfplumber", [PageText(**page) for page in pages])
    return data_root, work_root, pdf


def test_classification_selects_extraction_schema_for_unexpected_filename(tmp_path: Path):
    cached = read_cached(
        CACHE_ROOT, GOLD_DIR / "przyklad_01" / "odwolanie.pdf", "pdfplumber"
    )
    assert cached is not None
    data_root, work_root, pdf = _fake_pdf_with_cached_text(
        tmp_path, "przyklad_obcy", "skan_2026", cached["pages"]
    )
    seen: list[str] = []

    def transport(**kwargs):
        user = kwargs["messages"][1]["content"]
        seen.append(user)
        if "Skategoryzuj" in user:
            return _response("odwolanie")
        return _response(_gold_payload("przyklad_01", "odwolanie"))

    result = run_pipeline(
        experiment=replace(EXPERIMENT, classify_method="llm"),
        model=MODEL,
        specs=SPECS,
        data_root=data_root,
        work_root=work_root,
        run_dir=tmp_path / "run",
        set_ids=["przyklad_obcy"],
        client=LLMClient(MODEL, transport=transport),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.class_id == "odwolanie"
    assert outcome.pdf_path == pdf
    assert (result.run_dir / "przyklad_obcy" / "odwolanie.json").exists()
    assert any("Skategoryzuj" in user for user in seen)
    assert any("odwołanie do Prezesa KIO" in user for user in seen)


def test_unknown_class_produces_zero_byte_output_without_extraction(tmp_path: Path):
    pages = [{"n": 1, "text": "Ogłoszenie TED 2026/S 123-456", "width": 100, "height": 100}]
    data_root, work_root, pdf = _fake_pdf_with_cached_text(
        tmp_path, "przyklad_obcy", "faktura", pages
    )
    seen: list[str] = []

    def transport(**kwargs):
        user = kwargs["messages"][1]["content"]
        seen.append(user)
        if "Skategoryzuj" not in user:
            raise AssertionError("unknown document must not reach an extractor")
        return _response("nieznany")

    result = run_pipeline(
        experiment=replace(EXPERIMENT, classify_method="llm"),
        model=MODEL,
        specs=SPECS,
        data_root=data_root,
        work_root=work_root,
        run_dir=tmp_path / "run",
        set_ids=["przyklad_obcy"],
        client=LLMClient(MODEL, transport=transport),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 1
    assert result.outcomes[0].classification is None
    # Classification is an LLM call now; it must be counted even when no
    # extraction follows.
    assert result.llm_calls == 1
    assert len(seen) == 1
    rejected = result.run_dir / "przyklad_obcy" / "faktura.json"
    assert rejected.exists()
    assert rejected.stat().st_size == 0
    usage = json.loads((result.run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage[0]["calls"] == 1
    assert usage[0]["prompt_tokens"] == 500


def test_rejected_transfer_uses_gold_stem_for_output_and_classification(tmp_path: Path):
    pages = [{"n": 1, "text": "transfer", "width": 100, "height": 100}]
    # The PDF name passes the class_ids stem filter, but the LLM resolves the
    # document as a transfer -- a class the caller did not ask for.
    data_root, work_root, _pdf = _fake_pdf_with_cached_text(
        tmp_path, "przyklad_obcy", "odwolanie", pages
    )

    def transport(**kwargs):
        user = kwargs["messages"][1]["content"]
        if "Skategoryzuj" in user:
            return _response("potwierdzenie_przelewu")
        raise AssertionError("rejected document must not reach an extractor")

    result = run_pipeline(
        experiment=replace(EXPERIMENT, classify_method="llm"),
        model=MODEL,
        specs=SPECS,
        data_root=data_root,
        work_root=work_root,
        run_dir=tmp_path / "run",
        set_ids=["przyklad_obcy"],
        class_ids=["odwolanie"],
        client=LLMClient(MODEL, transport=transport),
        prompts=PromptSet(),
    )

    expected = result.run_dir / "przyklad_obcy" / "przelew.json"
    assert expected.exists()
    assert expected.stat().st_size == 0
    classifications = json.loads((result.run_dir / "classification.json").read_text(encoding="utf-8"))
    assert classifications == {"przyklad_obcy/przelew.json": "potwierdzenie_przelewu"}


def test_classification_llm_response_is_counted_in_usage(tmp_path: Path):
    pages = [{"n": 1, "text": "dokument", "width": 100, "height": 100}]
    data_root, work_root, _pdf = _fake_pdf_with_cached_text(
        tmp_path, "przyklad_obcy", "skan_2026", pages
    )

    def transport(**kwargs):
        user = kwargs["messages"][1]["content"]
        if "Skategoryzuj" in user:
            return _response("odwolanie")
        # Extraction may fail validation; its tokens still belong in usage.
        return _response("{}")

    result = run_pipeline(
        experiment=replace(EXPERIMENT, classify_method="llm", retry_on_invalid=0),
        model=MODEL,
        specs=SPECS,
        data_root=data_root,
        work_root=work_root,
        run_dir=tmp_path / "run",
        set_ids=["przyklad_obcy"],
        client=LLMClient(MODEL, transport=transport),
        prompts=PromptSet(),
    )

    assert not result.outcomes[0].ok
    assert result.llm_calls == 2
    assert result.prompt_tokens == 1000
    assert result.completion_tokens == 240
    usage = json.loads((result.run_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage[0]["calls"] == 2
    assert usage[0]["prompt_tokens"] == 1000
    assert usage[0]["structured_calls"] == 1


def test_polish_labels_are_mapped_for_models_without_structured_output(tmp_path: Path):
    polish_model = replace(
        MODEL, id="bielik-11b", no_think_suffix=None, structured_output=False
    )
    raw = (
        '{"Typ dokumentu": "potwierdzenie przelewu bankowego", '
        '"Płatnik": {"Nazwa": "Belmoria Rozwiązania S.A.", "Rachunek": "PL05470680287581539721455024"}, '
        '"Adresat przelewu": {"Nazwa": "Aurelink Automatyka S.A.", "Rachunek": "PL68438223049992295262834736"}, '
        '"Kwota operacji": 200.0, "Data transakcji": "2026-03-21", '
        '"Tytuł przelewu": "opłata skarbowa od pełnomocnictwa", "Nr ref.": "CEN2604016344389"}'
    )
    users: list[str] = []

    def transport(**kwargs):
        users.append(kwargs["messages"][1]["content"])
        return _response(raw)

    result = run_pipeline(
        experiment=EXPERIMENT,
        model=polish_model,
        specs={"potwierdzenie_przelewu": SPECS["potwierdzenie_przelewu"]},
        data_root=paths.data_root(),
        work_root=paths.work_root(),
        run_dir=tmp_path / "polish_run",
        set_ids=["przyklad_01"],
        class_ids=["potwierdzenie_przelewu"],
        client=LLMClient(polish_model, transport=transport),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.ok, outcome.extraction.error
    assert "WYŁĄCZNIE" in users[0]
    assert "przelew_bankowy.kwota" in users[0]
    pred = json.loads((result.run_dir / "przyklad_01" / "przelew.json").read_text(encoding="utf-8"))
    przelew = pred["przelew_bankowy"]
    assert przelew["kwota"] == 200.0
    assert przelew["na_rachunek"] == "68438223049992295262834736"
    assert przelew["z_rachunku"] == "05470680287581539721455024"
    assert przelew["numer_transakcji"] == "CEN2604016344389"


def test_flat_dotted_keys_and_extra_typ_are_normalized(tmp_path: Path):
    polish_model = replace(
        MODEL, id="bielik-11b", no_think_suffix=None, structured_output=False
    )
    raw = (
        '{"przelew_bankowy": "potwierdzenie przelewu bankowego", '
        '"przelew_bankowy.data_operacji": "2026-03-21", '
        '"przelew_bankowy.kwota": 200, '
        '"przelew_bankowy.na_rachunek": "PL68438223049992295262834736", '
        '"przelew_bankowy.numer_transakcji": "CEN2604016344389", '
        '"przelew_bankowy.tytul": "opłata skarbowa", '
        '"przelew_bankowy.z_rachunku": "PL05470680287581539721455024"}'
    )

    def transport(**kwargs):
        return _response(raw)

    result = run_pipeline(
        experiment=EXPERIMENT,
        model=polish_model,
        specs={"potwierdzenie_przelewu": SPECS["potwierdzenie_przelewu"]},
        data_root=paths.data_root(),
        work_root=paths.work_root(),
        run_dir=tmp_path / "flat_run",
        set_ids=["przyklad_01"],
        class_ids=["potwierdzenie_przelewu"],
        client=LLMClient(polish_model, transport=transport),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.ok, outcome.extraction.error
    pred = json.loads((result.run_dir / "przyklad_01" / "przelew.json").read_text(encoding="utf-8"))
    przelew = pred["przelew_bankowy"]
    assert przelew["kwota"] == 200.0
    assert przelew["na_rachunek"] == "68438223049992295262834736"
    assert "typ" not in przelew


def test_retry_repairs_invalid_json_and_records_one_retry(tmp_path: Path, index):
    calls: list[str] = []
    users: list[str] = []

    def transport(**kwargs):
        users.append(kwargs["messages"][1]["content"])
        if not calls:
            calls.append("broken")
            return _response('{"OdwolanieKIO": ')
        calls.append("odwolanie")
        return _response(_gold_payload("przyklad_01", "odwolanie"))

    result = run_pipeline(
        experiment=EXPERIMENT,
        model=MODEL,
        specs={"odwolanie": SPECS["odwolanie"]},
        data_root=paths.data_root(),
        work_root=paths.work_root(),
        run_dir=tmp_path / "retry_run",
        set_ids=["przyklad_01"],
        class_ids=["odwolanie"],
        client=LLMClient(MODEL, transport=transport),
        prompts=PromptSet(),
    )

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.ok
    assert outcome.extraction.retries == 1
    assert calls[0] == "broken"
    assert "błąd_walidacji" in users[1]
    assert (result.run_dir / "przyklad_01" / "odwolanie.json").exists()
    assert result.retries == 1


def _contaminated_extraction(field: str) -> tuple[object, str]:
    """Run `extract_document` on przyklad_02's gold with a CJK char injected.

    Returns (extraction, clean_gold_value) for the mutated field.
    """
    pdf = GOLD_DIR / "przyklad_02" / "odwolanie.pdf"
    cached = read_cached(CACHE_ROOT, pdf, "pdfplumber")
    assert cached is not None, f"missing cache for {pdf}; run `lab ingest` first"
    text = prepare_ocr_text(cached["pages"])

    gold = json.loads(_gold_payload("przyklad_02", "odwolanie"))
    clean = gold["OdwolanieKIO"][field]
    assert isinstance(clean, str) and len(clean) > 2
    mid = len(clean) // 2
    gold["OdwolanieKIO"][field] = clean[:mid] + "的" + clean[mid:]

    def transport(**kwargs):
        return _response(json.dumps(gold, ensure_ascii=False))

    extraction = extract_document(
        LLMClient(MODEL, transport=transport),
        PromptSet(),
        SPECS["odwolanie"],
        text,
    )
    return extraction, clean


def test_extract_document_strips_cjk_from_model_output():
    result, clean = _contaminated_extraction("miejscowosc")

    assert result.obj is not None, result.error
    assert result.error is None
    assert result.sanitized == 1
    assert result.retries == 0
    assert result.obj["OdwolanieKIO"]["miejscowosc"] == clean


def test_extract_document_rescues_cjk_in_enum_constrained_field():
    result, clean = _contaminated_extraction("czynnosc_opis")

    assert result.obj is not None, result.error
    assert result.error is None
    assert result.sanitized == 1
    assert result.retries == 0
    assert result.obj["OdwolanieKIO"]["czynnosc_opis"] == clean
