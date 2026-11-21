from pathlib import Path

import pytest

import lab.model_check as mc


def _make_data_root(base: Path, n_sets: int, with_scans: bool = False) -> Path:
    root = base / "data-root"
    dane = root / "dane"
    dane.mkdir(parents=True)
    for index in range(1, n_sets + 1):
        set_dir = dane / f"przyklad_{index:02d}"
        set_dir.mkdir()
        (set_dir / "odwolanie.pdf").write_bytes(b"%PDF")
        (set_dir / "odwolanie.json").write_text("{}", encoding="utf-8")
    if with_scans:
        scan_dir = dane / "skany" / "odwolania" / "0001"
        scan_dir.mkdir(parents=True)
        (scan_dir / "0001.pdf").write_bytes(b"%PDF")
        (scan_dir / "0001.json").write_text("{}", encoding="utf-8")
    return root


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
