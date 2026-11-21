import importlib
import json
import sys

import pytest
from typer.testing import CliRunner

import lab.cli
from lab import paths


def test_cli_imports_without_jiwer(monkeypatch):
    """`lab serve` must work without the research-only `lab` extra."""
    monkeypatch.setitem(sys.modules, "jiwer", None)
    importlib.reload(lab.cli)
    assert lab.cli.app is not None


def test_cli_import_restored():
    importlib.reload(lab.cli)


def test_model_check_command_is_registered():
    result = CliRunner().invoke(lab.cli.app, ["model-check", "--help"])
    assert result.exit_code == 0
    assert "--corpus" in result.output
    assert "--save-ocr" not in result.output


def _data_root(tmp_path):
    data_root = tmp_path / "data"
    set_dir = data_root / "dane" / "przyklad_01"
    set_dir.mkdir(parents=True)
    for stem in ("odwolanie", "pelnomocnictwo", "przelew"):
        (set_dir / f"{stem}.json").write_text("{}", encoding="utf-8")
    return data_root


def test_eval_refuses_missing_run_dir_without_explicit_flag(tmp_path):
    data_root = _data_root(tmp_path)
    missing_run = tmp_path / "does_not_exist"

    result = CliRunner().invoke(
        lab.cli.app, ["eval", "--run", str(missing_run), "--data-root", str(data_root)]
    )

    assert result.exit_code != 0
    assert "--pred-equals-gold" in result.output


def test_eval_runs_identity_only_with_explicit_flag(tmp_path):
    data_root = _data_root(tmp_path)
    run_dir = tmp_path / "identity_run"

    result = CliRunner().invoke(
        lab.cli.app,
        ["eval", "--run", str(run_dir), "--data-root", str(data_root), "--pred-equals-gold"],
    )

    assert result.exit_code == 0, result.output
    assert "gold against itself" in result.output
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["n_files_evaluated"] == 3


def test_eval_existing_run_does_not_trigger_identity(tmp_path):
    data_root = _data_root(tmp_path)
    run_dir = tmp_path / "real_run"
    run_dir.mkdir()

    result = CliRunner().invoke(
        lab.cli.app, ["eval", "--run", str(run_dir), "--data-root", str(data_root)]
    )

    assert result.exit_code == 0, result.output
    assert "gold against itself" not in result.output
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["missing_pred"] == 3


def test_data_root_validation_and_override(monkeypatch, tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(FileNotFoundError, match="O2J_DATA_ROOT"):
        paths.validate_data_root(missing)

    existing = tmp_path / "present"
    existing.mkdir()
    monkeypatch.setenv("O2J_DATA_ROOT", str(existing))
    assert paths.data_root(must_exist=True) == existing


def test_ingest_rejects_data_root_with_no_pdfs(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    result = CliRunner().invoke(lab.cli.app, ["ingest", "--data-root", str(empty_root)])

    assert result.exit_code != 0
    assert "no PDFs found" in result.output
