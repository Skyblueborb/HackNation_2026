"""CLI: single PDF -> OCR -> LLM -> JSON, with server health checks."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from ocr_common import render_pages
from ocr_common.ports import OCRDocument, OCRPage

DEFAULT_OCR_MODEL = "models/LightOnOCR-3-0.8B-mlx-8bit"
DEFAULT_LLM_PROFILE = "local-llm"


def llm_health(base_url: str) -> bool:
    root = base_url.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/health", timeout=5) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def backend_health() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def check_servers(ocr_model_path: Path, llm_profile: str) -> str:
    """Verify required servers and weights. Return the LLM base URL."""
    from lab.llm.config import load_models
    from lab.paths import REPO_ROOT

    models = load_models(REPO_ROOT / "configs" / "models.yaml")
    if llm_profile not in models:
        available = ", ".join(sorted(models))
        raise RuntimeError(
            f"unknown LLM profile {llm_profile!r}; available: {available}"
        )
    base_url = models[llm_profile].base_url
    if not llm_health(base_url):
        raise RuntimeError(
            f"LLM server for profile {llm_profile} is not running at {base_url}. "
            f"Start it with: uv run lab serve --model {llm_profile}"
        )
    if not Path(ocr_model_path).exists():
        raise RuntimeError(
            f"OCR weights not found: {ocr_model_path}. "
            "Run: bash scripts/make-mlx-model-08b.sh"
        )
    return base_url


def _load_backend():
    from local_ai.app import MlxBackend

    return MlxBackend()


def _load_processor():
    from ocr_api.llm_processor import get_processor

    return get_processor()


def run_document(
    data: bytes, filename: str, model_id: str
) -> tuple[dict[str, Any], dict[str, float]]:
    t0 = time.perf_counter()
    images = render_pages(data)
    t1 = time.perf_counter()

    backend = _load_backend()
    texts = [backend.extract_page(image).strip() for image in images]
    t2 = time.perf_counter()

    document = OCRDocument(
        backend="mlx",
        model=model_id,
        pages=tuple(OCRPage(number=i, text=text) for i, text in enumerate(texts, 1)),
        filename=filename,
    )
    llm = _load_processor().process(document)
    t3 = time.perf_counter()

    if isinstance(llm, dict) and isinstance(llm.get("data"), dict):
        result = llm["data"]
    else:
        result = {"raw_text": "\n\n".join(texts)}

    return result, {
        "render": t1 - t0,
        "ocr": t2 - t1,
        "llm": t3 - t2,
        "total": t3 - t0,
    }


def write_result(pdf: Path, result: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{pdf.stem}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="ocr-pdf2json")
    parser.add_argument("pdf", type=Path, help="single PDF to process")
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--ocr-model",
        default=os.environ.get("MLX_MODEL", DEFAULT_OCR_MODEL),
        help="local MLX weights path",
    )
    parser.add_argument(
        "--llm-profile",
        default=os.environ.get("OCR_LLM_MODEL", DEFAULT_LLM_PROFILE),
        help="key in configs/models.yaml",
    )
    args = parser.parse_args()

    os.environ["MLX_MODEL"] = args.ocr_model
    os.environ["OCR_LLM_MODEL"] = args.llm_profile
    os.environ.setdefault("API_KEY", "local-cli")

    base_url = check_servers(Path(args.ocr_model), args.llm_profile)
    print(f"[ok] LLM {args.llm_profile}: {base_url}")
    print(f"[ok] OCR weights: {args.ocr_model}")
    print(f"[i] backend API: {'running' if backend_health() else 'not needed/stopped'}")

    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")

    result, timings = run_document(
        args.pdf.read_bytes(), args.pdf.name, args.ocr_model
    )
    out = write_result(args.pdf, result, args.out_dir)

    print(
        f"render={timings['render']:.2f}s ocr={timings['ocr']:.2f}s "
        f"llm={timings['llm']:.2f}s total={timings['total']:.2f}s"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
