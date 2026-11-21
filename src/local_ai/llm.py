"""CLI for running the local llama.cpp LLM server (no LLM logic here).

Wraps `lab.llm.server.ensure_server` around a model profile from
`configs/models.yaml`, so developer and production runs share one server
lifecycle. The OCR API talks to the resulting OpenAI-compatible endpoint.
"""

from __future__ import annotations

import argparse
import re
import threading
from dataclasses import replace

from lab import paths
from lab.llm.config import ModelConfig, load_models
from lab.llm.server import ensure_server, stop_server

DEFAULT_MODEL = "local-llm"
_NGL_RE = re.compile(r"-ngl\s+\d+")


def _cpu_flags(flags: str) -> str:
    """Turn off GPU offload while keeping the rest of the server flags."""
    if _NGL_RE.search(flags):
        return _NGL_RE.sub("-ngl 0", flags)
    return f"{flags} -ngl 0".strip()


def build_local_config(
    model_id: str = DEFAULT_MODEL, cpu: bool = False, port: int | None = None
) -> ModelConfig:
    """Build a ModelConfig from a profile, with optional CPU/port overrides."""
    models = load_models(paths.configs_root() / "models.yaml")
    if model_id not in models:
        raise ValueError(
            f"unknown model {model_id!r}; available: {', '.join(sorted(models))}"
        )
    config = models[model_id]
    changes: dict[str, object] = {}
    if cpu:
        changes["server_flags"] = _cpu_flags(config.server_flags)
    if port is not None:
        changes["port"] = port
        changes["base_url"] = f"http://localhost:{port}/v1"
    return replace(config, **changes)


def _serve(model_id: str, cpu: bool, port: int | None) -> None:
    config = build_local_config(model_id, cpu=cpu, port=port)
    proc = ensure_server(config, paths.work_root())
    print(f"OpenAI-compatible endpoint: {config.base_url}")
    print(f"Model id: {config.model}")
    print("Ctrl-C to stop.")
    try:
        if proc is not None:
            proc.wait()
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(proc)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="local-llm")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local LLM server in the foreground")
    serve.add_argument("--model", default=DEFAULT_MODEL, help="model id from configs/models.yaml")
    serve.add_argument(
        "--cpu", action="store_true", help="CPU fallback: offload zero layers (-ngl 0)"
    )
    serve.add_argument("--port", type=int, default=None, help="override the server port/base_url")
    args = parser.parse_args(argv)

    if args.command == "serve":
        _serve(args.model, args.cpu, args.port)


if __name__ == "__main__":
    main()
