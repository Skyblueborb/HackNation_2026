from lab import paths


def test_relative_data_root_is_resolved_from_repo_root(monkeypatch, tmp_path):
    monkeypatch.delenv("O2J_DATA_ROOT", raising=False)
    monkeypatch.setattr(paths, "_config", lambda: {"data_root": "../fixture-data"})
    monkeypatch.chdir(tmp_path)
    assert paths.data_root() == paths.REPO_ROOT.parent / "fixture-data"
