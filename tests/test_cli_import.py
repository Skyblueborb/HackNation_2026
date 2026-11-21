import importlib
import sys

import pytest

import lab.cli


def test_cli_imports_without_jiwer(monkeypatch):
    """`lab serve` must work without the research-only `lab` extra."""
    monkeypatch.setitem(sys.modules, "jiwer", None)
    importlib.reload(lab.cli)
    assert lab.cli.app is not None


def test_cli_import_restored():
    importlib.reload(lab.cli)
