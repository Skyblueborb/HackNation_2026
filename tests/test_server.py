"""Tests for the one-server-at-a-time lifecycle helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab import paths
from lab.llm.config import load_models
from lab.llm.server import ensure_server, server_command, stop_server


class FakeProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode if self.returncode is not None else 0


def test_server_command_uses_per_model_flags():
    models = load_models(paths.configs_root() / "models.yaml")
    cmd = server_command(models["qwen3-8b"])

    assert cmd[:5] == ["llama-server", "-hf", models["qwen3-8b"].hf_repo, "--port", "8082"]
    assert "-c" in cmd and "6144" in cmd
    assert "-ngl" in cmd and "24" in cmd
    assert "--parallel" in cmd and "1" in cmd


def test_bielik_disables_response_format():
    models = load_models(paths.configs_root() / "models.yaml")
    assert models["bielik-11b"].structured_output is False
    assert models["qwen3-4b"].structured_output is True


def test_ensure_server_reuses_an_healthy_server(monkeypatch, tmp_path: Path):
    model = load_models(paths.configs_root() / "models.yaml")["qwen3-4b"]
    monkeypatch.setattr("lab.llm.server.health_ok", lambda _: True)

    def fail_start(*args, **kwargs):
        raise AssertionError("should not start a second server")

    monkeypatch.setattr("lab.llm.server.subprocess.Popen", fail_start)
    assert ensure_server(model, tmp_path) is None


def test_ensure_server_starts_when_health_becomes_ok(monkeypatch, tmp_path: Path):
    model = load_models(paths.configs_root() / "models.yaml")["qwen3-4b"]
    proc = FakeProc()
    states = iter([False, True])
    monkeypatch.setattr("lab.llm.server.health_ok", lambda _: next(states))
    monkeypatch.setattr("lab.llm.server.subprocess.Popen", lambda *a, **k: proc)
    monkeypatch.setattr("lab.llm.server.time.sleep", lambda _: None)

    assert ensure_server(model, tmp_path, timeout=10) is proc
    assert proc.terminated is False
    assert (tmp_path / "servers" / "qwen3-4b.log").parent.is_dir()


def test_ensure_server_stops_when_start_times_out(monkeypatch, tmp_path: Path):
    model = load_models(paths.configs_root() / "models.yaml")["qwen3-4b"]
    proc = FakeProc()
    monkeypatch.setattr("lab.llm.server.health_ok", lambda _: False)
    monkeypatch.setattr("lab.llm.server.subprocess.Popen", lambda *a, **k: proc)
    monkeypatch.setattr("lab.llm.server.time.sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="did not become healthy"):
        ensure_server(model, tmp_path, timeout=0.001)
    assert proc.terminated is True


def test_ensure_server_extends_deadline_while_download_is_progressing(monkeypatch, tmp_path: Path):
    model = load_models(paths.configs_root() / "models.yaml")["qwen3-4b"]
    proc = FakeProc()
    clock = [0.0]
    progress_written = [False]
    log_path = tmp_path / "servers" / "qwen3-4b.log"

    def fake_health(_):
        if clock[0] >= 4 and not progress_written[0]:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("Downloading model 42%\n")
            progress_written[0] = True
        return False

    monkeypatch.setattr("lab.llm.server.health_ok", fake_health)
    monkeypatch.setattr("lab.llm.server.subprocess.Popen", lambda *a, **k: proc)
    monkeypatch.setattr("lab.llm.server.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "lab.llm.server.time.sleep", lambda _: clock.__setitem__(0, clock[0] + 1)
    )

    with pytest.raises(RuntimeError, match="download did not finish"):
        ensure_server(model, tmp_path, timeout=5)

    assert progress_written[0] is True
    assert clock[0] >= 9
    assert proc.terminated is True


def test_stop_server_terminates_only_live_processes():
    live = FakeProc()
    stop_server(live)
    assert live.terminated is True

    dead = FakeProc()
    dead.returncode = 0
    stop_server(dead)
    assert dead.terminated is False
