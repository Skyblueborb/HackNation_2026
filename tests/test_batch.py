import json

import pytest

import ocr_api.batch as batch


def test_result_json_keeps_extraction():
    assert batch.result_json({"llm": {"data": {"sygnatura": "KIO 1/26"}}}) == {
        "sygnatura": "KIO 1/26"
    }


@pytest.mark.parametrize(
    "response",
    [
        {},                                        # processor disabled
        {"llm": None},                             # no LLM answer
        {"llm": {"rejected": True, "data": {}}},   # negative document
        {"llm": {"data": None}},                   # malformed answer
    ],
)
def test_result_json_is_empty_when_no_class_matched(response):
    assert batch.result_json(response) == {}


def test_llm_error_separates_a_dead_llm_from_a_negative_document():
    assert batch.llm_error({"llm": {"rejected": True, "error": None}}) is None
    assert batch.llm_error({"llm": {"error": "connection refused"}}) == "connection refused"
    assert batch.llm_error({}) is None


def test_pdfs_under_walks_cases_and_ignores_other_files(tmp_path):
    (tmp_path / "case2").mkdir()
    (tmp_path / "case1").mkdir()
    for name in ("case1/odwolanie.pdf", "case2/PRZELEW.PDF", "case1/notes.txt"):
        (tmp_path / name).write_bytes(b"x")

    found = [path.relative_to(tmp_path).as_posix() for path in batch.pdfs_under(tmp_path)]
    assert found == ["case1/odwolanie.pdf", "case2/PRZELEW.PDF"]


def test_main_mirrors_input_tree_and_survives_one_bad_document(tmp_path, monkeypatch):
    source = tmp_path / "input" / "case1"
    source.mkdir(parents=True)
    (source / "good.pdf").write_bytes(b"x")
    (source / "bad.pdf").write_bytes(b"x")

    def fake_process(pdf, processor):
        if pdf.name == "bad.pdf":
            raise RuntimeError("LLM down")
        return {"llm": {"data": {"sygnatura": "KIO 1/26"}, "error": None}}

    monkeypatch.setattr(batch, "process", fake_process)
    monkeypatch.setattr(batch, "load_llm_processor", lambda spec: object())
    monkeypatch.setattr(
        "sys.argv",
        ["ocr-batch", "--input", str(tmp_path / "input"), "--output", str(tmp_path / "output")],
    )

    batch.main()

    out = tmp_path / "output" / "case1"
    assert json.loads((out / "good.json").read_text()) == {"sygnatura": "KIO 1/26"}
    assert json.loads((out / "bad.json").read_text()) == {}
