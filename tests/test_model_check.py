import io
import json
import logging
from pathlib import Path

import httpx
import pytest
from PIL import Image

import lab.model_check as mc


def _pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


def _make_data_root(base: Path, n_sets: int, with_scans: bool = False) -> Path:
    root = base / "data-root"
    dane = root / "dane"
    dane.mkdir(parents=True)
    for index in range(1, n_sets + 1):
        set_dir = dane / f"przyklad_{index:02d}"
        set_dir.mkdir()
        (set_dir / "odwolanie.pdf").write_bytes(_pdf_bytes())
        (set_dir / "odwolanie.json").write_text("{}", encoding="utf-8")
    if with_scans:
        scan_dir = dane / "skany" / "odwolania" / "0001"
        scan_dir.mkdir(parents=True)
        (scan_dir / "0001.pdf").write_bytes(_pdf_bytes())
        (scan_dir / "0001.json").write_text("{}", encoding="utf-8")
    return root


def _make_borbelka_root(base: Path) -> Path:
    root = base / "borbelka-root"
    borbelka = root / "testy-dla-borbelka"
    for set_name, gold in (
        ("01", '{"OdwolanieKIO": {}}'),
        ("-1", "{}"),
    ):
        set_dir = borbelka / set_name
        set_dir.mkdir(parents=True)
        pdf = set_dir / f"{set_name.replace('-', 'n')}.pdf"
        pdf.write_bytes(_pdf_bytes())
        pdf.with_suffix(".json").write_text(gold, encoding="utf-8")
    return root


def test_discover_sets_borbelka(tmp_path):
    root = _make_borbelka_root(tmp_path)
    assert mc.discover_sets(root, "borbelka") == ["borbelka_-1", "borbelka_01"]


def test_select_documents_borbelka_random(tmp_path):
    root = _make_borbelka_root(tmp_path)
    cases = mc.select_documents(
        root, corpus="borbelka", count=2, random_sample=True, seed=42,
        sets=None, pdf_paths=None,
    )
    assert {case.set_id for case in cases} == {"borbelka_-1", "borbelka_01"}
    assert any(case.class_id == "nieznany" for case in cases)


def test_select_documents_count_first(tmp_path):
    root = _make_data_root(tmp_path, n_sets=3)
    cases = mc.select_documents(
        root, corpus="przyklad", count=2, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )
    assert [c.set_id for c in cases] == ["przyklad_01", "przyklad_02"]


def test_select_documents_random_is_seeded(tmp_path):
    root = _make_data_root(tmp_path, n_sets=5)
    kwargs = dict(
        corpus="przyklad", count=3, random_sample=True, seed=7,
        sets=None, pdf_paths=None,
    )
    assert [c.set_id for c in mc.select_documents(root, **kwargs)] == [
        c.set_id for c in mc.select_documents(root, **kwargs)
    ]


def test_select_documents_explicit_sets(tmp_path):
    root = _make_data_root(tmp_path, n_sets=3)
    cases = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=["przyklad_03"], pdf_paths=None,
    )
    assert [c.set_id for c in cases] == ["przyklad_03"]


def test_select_documents_explicit_pdf_maps_to_set_and_class(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    pdf = root / "dane" / "przyklad_01" / "odwolanie.pdf"
    cases = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )
    assert cases[0].set_id == "przyklad_01"
    assert cases[0].class_id == "odwolanie"
    assert cases[0].gold.name == "odwolanie.json"


def test_select_documents_accepts_pdf_with_sidecar_gold(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    pdf = outside / "abc123.pdf"
    pdf.write_bytes(_pdf_bytes())
    pdf.with_suffix(".json").write_text(
        '{"OdwolanieKIO": {}}', encoding="utf-8"
    )
    cases = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )
    assert cases[0].gold_stem == "odwolanie"
    assert cases[0].class_id == "odwolanie"
    assert cases[0].set_id == "local_abc123"
    assert cases[0].corpus == "local"


def test_select_documents_accepts_empty_sidecar_as_reject(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    outside = tmp_path / "rejects"
    outside.mkdir()
    pdf = outside / "reject.pdf"
    pdf.write_bytes(_pdf_bytes())
    pdf.with_suffix(".json").write_text("[]", encoding="utf-8")
    case = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )[0]
    assert case.class_id == "nieznany"
    assert case.gold_stem == "rejected"


def test_select_documents_accepts_empty_dict_sidecar_as_reject(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    outside = tmp_path / "rejects-dict"
    outside.mkdir()
    pdf = outside / "reject-dict.pdf"
    pdf.write_bytes(_pdf_bytes())
    pdf.with_suffix(".json").write_text("{}", encoding="utf-8")
    case = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )[0]
    assert case.class_id == "nieznany"
    assert case.gold_stem == "rejected"


def test_score_combo_scores_reject_case(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    outside = tmp_path / "rejects2"
    outside.mkdir()
    pdf = outside / "reject2.pdf"
    pdf.write_bytes(_pdf_bytes())
    pdf.with_suffix(".json").write_text("[]", encoding="utf-8")
    case = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )[0]
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "rejected.json").write_text("{}", encoding="utf-8")
    out = mc.score_combo([case], combo, mc._specs_with_reject(), [case.set_id])
    assert out["n_files_evaluated"] == 1


def test_score_combo_scores_sidecar_case_with_expected_gold_stem(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    outside = tmp_path / "outside2"
    outside.mkdir()
    pdf = outside / "xyz789.pdf"
    pdf.write_bytes(_pdf_bytes())
    gold = pdf.with_suffix(".json")
    gold.write_text('{"OdwolanieKIO": {}}', encoding="utf-8")
    case = mc.select_documents(
        root, corpus="przyklad", count=5, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )[0]
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text("{}", encoding="utf-8")
    out = mc.score_combo([case], combo, mc._specs(), [case.set_id])
    assert out["n_files_evaluated"] == 1


def test_select_documents_rejects_pdf_outside_data_root(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    stray = tmp_path / "stray.pdf"
    stray.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="data_root"):
        mc.select_documents(
            root, corpus="przyklad", count=5, random_sample=False, seed=42,
            sets=None, pdf_paths=[stray],
        )


def test_scan_cases_have_no_text_layer(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1, with_scans=True)
    cases = mc.select_documents(
        root, corpus="skany", count=0, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )
    assert cases
    assert all(c.corpus == "skany" and not c.has_text_layer for c in cases)


def test_potwierdzenie_pdf_maps_to_przelew_gold(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    pdf = root / "dane" / "przyklad_01" / "potwierdzenie_przelewu.pdf"
    pdf.write_bytes(b"%PDF")
    cases = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=[pdf],
    )
    assert cases[0].class_id == "potwierdzenie_przelewu"
    assert cases[0].gold.name == "przelew.json"


def test_run_case_remote_uses_backend_proxy(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "backend": "remote",
                "pages": [{"page": 1, "text": "REMOTE OCR"}],
                "canonical_json": {"ok": True},
            }

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx, "post", fake_post)
    try:
        row = mc.run_case_remote(
            case,
            remote_url="http://127.0.0.1:8000",
            api_token="tok",
            client_token="harness",
            combo_dir=tmp_path / "combo",
        )
    finally:
        monkeypatch.undo()

    assert captured["url"] == "http://127.0.0.1:8000/api/analyze"
    assert captured["headers"]["X-API-Token"] == "tok"
    assert captured["data"]["doc_class"] == "odwolanie"
    assert row["timings"]["total"] >= 0
    pred = tmp_path / "combo" / "predictions" / case.set_id / "odwolanie.json"
    assert json.loads(pred.read_text()) == {"ok": True}
    ocr = tmp_path / "combo" / "ocr" / case.set_id / "odwolanie.ocr.txt"
    assert "REMOTE OCR" in ocr.read_text()


def test_run_case_e2e_writes_ocr_artifact_and_prediction(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]

    class FakeBackend:
        def extract_page(self, image):
            return "ODWOLANIE TEXT"

    class FakeProcessor:
        def process(self, document):
            return {"class": "odwolanie", "data": {"ok": True}}

    combo = tmp_path / "combo"
    row = mc.run_case(
        case, ocr_model="fake", llm_profile="fake", analysis="e2e",
        combo_dir=combo, backend=FakeBackend(), processor=FakeProcessor(),
    )
    assert (combo / "ocr" / case.set_id / "odwolanie.ocr.txt").exists()
    assert (combo / "predictions" / case.set_id / "odwolanie.json").exists()
    assert row["timings"]["llm"] >= 0


def test_run_case_ocr_only_skips_llm(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]

    class FakeBackend:
        def extract_page(self, image):
            return "TEXT"

    row = mc.run_case(
        case, ocr_model="fake", llm_profile=None, analysis="ocr",
        combo_dir=tmp_path / "combo", backend=FakeBackend(), processor=None,
    )
    assert row["timings"]["llm"] == 0.0
    assert row["prediction"] is None


def test_scan_llm_probe_is_na(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1, with_scans=True)
    case = mc.select_documents(
        root, corpus="skany", count=0, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    result = mc.run_case(
        case, ocr_model="fake", llm_profile="fake", analysis="llm",
        combo_dir=tmp_path / "combo", backend=None, processor=object(),
    )
    assert result["status"] == "N/A"


def test_write_summary_uses_absolute_report_paths(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    mc.write_summary(
        run_dir,
        [
            {
                "analysis": "e2e",
                "ocr_model": "text",
                "llm_profile": "local-llm",
                "n_files_evaluated": 1,
                "exact_f1_skip": 0.5,
                "fuzzy_f1_skip": 0.5,
                "ocr_proxy": {"cer_mean": "N/A"},
                "speed": {"total": {"mean": 1.0}},
                "combo_dir": "e2e/text/local-llm",
                "field_groups": {},
            }
        ],
    )
    report = (run_dir / "e2e/text/local-llm/report.md").resolve()
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert f"[report.md]({report})" in summary


def test_configure_logging_disables_propagation():
    mc.configure_logging(False)
    assert mc.logger.propagate is False


def test_jsonable_handles_path_lists(tmp_path):
    payload = mc._jsonable(
        {"data_root": tmp_path, "pdf_paths": [tmp_path / "a.pdf", tmp_path / "b.pdf"]}
    )
    assert json.loads(json.dumps(payload))["pdf_paths"] == [
        str(tmp_path / "a.pdf"),
        str(tmp_path / "b.pdf"),
    ]


def test_select_documents_records_missing_pdf(tmp_path):
    root = _make_data_root(tmp_path, n_sets=2)
    (root / "dane" / "przyklad_02" / "odwolanie.pdf").unlink()
    missing: list[str] = []
    mc.select_documents(
        root, corpus="przyklad", count=0, random_sample=False, seed=42,
        sets=None, pdf_paths=None, missing=missing,
    )
    assert "przyklad_02" in missing


def test_select_documents_rejects_missing_explicit_pdf(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    absent = root / "dane" / "przyklad_01" / "absent.pdf"
    with pytest.raises(ValueError, match="PDF not found"):
        mc.select_documents(
            root, corpus="przyklad", count=1, random_sample=False, seed=42,
            sets=None, pdf_paths=[absent],
        )


def test_run_case_logs_progress(caplog, tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]

    class FakeBackend:
        def extract_page(self, image):
            return "TEXT"

    with caplog.at_level(logging.INFO, logger="lab.model_check"):
        mc.run_case(
            case, ocr_model="fake", llm_profile=None, analysis="ocr",
            combo_dir=tmp_path / "combo", backend=FakeBackend(), processor=None,
        )
    assert "przyklad_01" in caplog.text
    assert "ocr" in caplog.text.lower()


def test_aggregate_speed_known_values():
    rows = [{"timings": {"ocr": 1.0}}, {"timings": {"ocr": 3.0}}]
    out = mc.aggregate_speed(rows, ["ocr"])
    assert out["ocr"]["mean"] == 2.0
    assert out["ocr"]["sum"] == 4.0


def test_score_combo_writes_metrics_and_report(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text("{}", encoding="utf-8")
    result = mc.score_combo([case], combo, mc._specs(), [case.set_id])
    assert (combo / "metrics.json").exists()
    assert (combo / "report.md").exists()
    assert "f1_skip" in str(result)


def test_field_groups_split_text_and_strict_values(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    case.gold.write_text(
        json.dumps(
            {
                "OdwolanieKIO": {
                    "data": "2026-09-03",
                    "czynnosc_dzien": "2026-08-22",
                    "miejscowosc": "Gdansk",
                },
                "Odwolujacy": [{"krs": "9999669444", "nazwa": "Hartica"}],
            }
        ),
        encoding="utf-8",
    )
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text(
        json.dumps(
            {
                "OdwolanieKIO": {
                    "data": "2026-09-03",
                    "czynnosc_dzien": "2026-08-22",
                    "miejscowosc": "Warszawa",
                },
                "Odwolujacy": [{"krs": "0000000000", "nazwa": "Hartica"}],
            }
        ),
        encoding="utf-8",
    )
    result = mc.score_combo([case], combo, mc._specs(), [case.set_id])
    groups = result["field_groups"]
    assert groups["date"]["binary_f1"] == 1.0
    assert groups["identifier"]["field_scores"]["Odwolujacy[].krs"] == 0
    assert groups["identifier"]["binary_f1"] < 1.0
    assert groups["text"]["exact_f1_skip"] < 1.0
    assert (combo / "report.md").read_text(encoding="utf-8").find("Field groups") >= 0


def test_score_combo_report_includes_documents_and_ocr_text(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    case.gold.write_text(
        '{"OdwolanieKIO": {"miejscowosc": "Gdansk", "data": "2026-09-03"}}',
        encoding="utf-8",
    )
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text(
        '{"OdwolanieKIO": {"miejscowosc": "Warszawa", "data": "2026-09-03"}}',
        encoding="utf-8",
    )
    ocr_dir = combo / "ocr" / case.set_id
    ocr_dir.mkdir(parents=True)
    (ocr_dir / "odwolanie.ocr.txt").write_text("RAW OCR MARKER\n", encoding="utf-8")

    mc.score_combo([case], combo, mc._specs(), [case.set_id])
    report = (combo / "report.md").read_text(encoding="utf-8")
    assert "RAW OCR MARKER" in report
    assert "GOLD JSON" in report
    assert "PREDICTED JSON" in report
    assert "Correct fields" in report
    assert "Wrong fields" in report
    assert "Warszawa" in report
    assert "Gdansk" in report


def test_score_combo_logs_mismatch_details(caplog, tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    case.gold.write_text('{"OdwolanieKIO": {"miejscowosc": "Gdansk"}}', encoding="utf-8")
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text(
        '{"OdwolanieKIO": {"miejscowosc": "Warszawa"}}', encoding="utf-8"
    )
    with caplog.at_level(logging.INFO, logger="lab.model_check"):
        mc.score_combo([case], combo, mc._specs(), [case.set_id])
    assert "MISMATCH" in caplog.text
    assert "Warszawa" in caplog.text


def test_score_combo_report_survives_a_field_mismatch(tmp_path):
    root = _make_data_root(tmp_path, n_sets=1)
    case = mc.select_documents(
        root, corpus="przyklad", count=1, random_sample=False, seed=42,
        sets=None, pdf_paths=None,
    )[0]
    case.gold.write_text(
        '{"OdwolanieKIO": {"miejscowosc": "Gdansk"}}', encoding="utf-8"
    )
    combo = tmp_path / "combo"
    pred_dir = combo / "predictions" / case.set_id
    pred_dir.mkdir(parents=True)
    (pred_dir / "odwolanie.json").write_text(
        '{"OdwolanieKIO": {"miejscowosc": "Warszawa"}}', encoding="utf-8"
    )
    mc.score_combo([case], combo, mc._specs(), [case.set_id])
    report = (combo / "report.md").read_text(encoding="utf-8")
    assert "Warszawa" in report
    assert "Gdansk" in report
