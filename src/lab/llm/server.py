"""Start and stop exactly one local llama-server at a time."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from lab.llm.client import LLMClient
from lab.llm.config import ModelConfig

START_TIMEOUT = 900.0
_DOWNLOAD_PROGRESS_RE = re.compile(r"(?i)(download|downloading|fetch|pulling|\b\d{1,3}\s*%)")


def _read_log_chunk(log_path: Path, offset: int) -> tuple[str, int]:
    try:
        with log_path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
            return data.decode("utf-8", "replace"), handle.tell()
    except FileNotFoundError:
        return "", offset


def server_command(model: ModelConfig) -> list[str]:
    if not model.hf_repo:
        raise ValueError(f"model {model.id!r} has no hf_repo; cannot start a server")
    if model.port is None:
        raise ValueError(f"model {model.id!r} has no port; cannot start a server")
    return [
        "llama-server",
        "-hf",
        model.hf_repo,
        "--port",
        str(model.port),
        *shlex.split(model.server_flags),
    ]


def health_ok(model: ModelConfig) -> bool:
    return bool(LLMClient(model).health()["ok"])


def stop_server(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def ensure_server(
    model: ModelConfig, work_root: Path, *, timeout: float = START_TIMEOUT
) -> subprocess.Popen[bytes] | None:
    if health_ok(model):
        return None

    log_path = work_root / "servers" / f"{model.id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        last_offset = log_path.stat().st_size
        try:
            proc = subprocess.Popen(
                server_command(model), stdout=log, stderr=subprocess.STDOUT
            )
        except FileNotFoundError as exc:
            raise RuntimeError("llama-server not found in PATH") from exc
        deadline = time.monotonic() + timeout
        saw_download = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"{model.id}: llama-server exited early; see {log_path}")
            if health_ok(model):
                return proc
            chunk, last_offset = _read_log_chunk(log_path, last_offset)
            if chunk and _DOWNLOAD_PROGRESS_RE.search(chunk):
                saw_download = True
                deadline = time.monotonic() + timeout
            time.sleep(1)
    stop_server(proc)
    if saw_download:
        raise RuntimeError(
            f"{model.id}: model download did not finish in {timeout:.0f}s; see {log_path}"
        )
    raise RuntimeError(
        f"{model.id}: llama-server did not become healthy in {timeout:.0f}s; see {log_path}"
    )
