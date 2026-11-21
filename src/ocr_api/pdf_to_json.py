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

LLM_HEALTH_TIMEOUT = float(os.environ.get("OCR_LLM_HEALTH_TIMEOUT", "5"))
# Match LLMClient's default 900s timeout so a long extraction is not cut short.
REMOTE_TIMEOUT = float(os.environ.get("OCR_REMOTE_TIMEOUT", "900.0"))


def llm_health(base_url: str, timeout: float = LLM_HEALTH_TIMEOUT) -> bool:
    root = base_url.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/health", timeout=timeout) as response:
            return response.status == 200
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

    if isinstance(llm, dict) and llm.get("rejected"):
        # Document doesn't match any of the three known classes -- empty
        # result, not a guessed extraction.
        result: dict[str, Any] = {}
    elif isinstance(llm, dict) and isinstance(llm.get("data"), dict):
        result = llm["data"]
    else:
        result = {"raw_text": "\n\n".join(texts)}

    return result, {
        "render": t1 - t0,
        "ocr": t2 - t1,
        "llm": t3 - t2,
        "total": t3 - t0,
    }


def doc_class_from_filename(pdf: Path) -> str:
    name = pdf.stem.lower()
    if "odwol" in name or "odwoł" in name:
        return "odwolanie"
    if "pelnom" in name or "pełnom" in name:
        return "pelnomocnictwo"
    if "przelew" in name or "platn" in name or "trans" in name:
        return "przelew"
    return "odwolanie"


def post_analyze(
    *,
    base_url: str,
    pdf: Path,
    token: str | None,
    doc_class: str,
    client_token: str,
    client_doc_id: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST one PDF to a remote backend /api/analyze."""
    import httpx

    headers = {"X-API-Token": token} if token else {}
    url = f"{base_url.rstrip('/')}/api/analyze"
    with pdf.open("rb") as handle:
        response = httpx.post(
            url,
            data={
                "client_token": client_token,
                "client_doc_id": client_doc_id,
                "doc_class": doc_class,
            },
            files={"file": (pdf.name, handle, "application/pdf")},
            headers=headers,
            timeout=REMOTE_TIMEOUT if timeout is None else timeout,
        )
    response.raise_for_status()
    return response.json()


def run_remote(
    pdf: Path,
    base_url: str,
    token: str | None,
    *,
    doc_class: str | None = None,
    client_token: str = "cli-remote",
) -> tuple[dict[str, Any], dict[str, float]]:
    started = time.perf_counter()
    response = post_analyze(
        base_url=base_url,
        pdf=pdf,
        token=token,
        doc_class=doc_class or doc_class_from_filename(pdf),
        client_token=client_token,
        client_doc_id=f"cli-{pdf.stem}",
    )
    elapsed = time.perf_counter() - started
    canonical = response.get("canonical_json")
    if not isinstance(canonical, dict):
        pages = response.get("pages", [])
        canonical = {
            "raw_text": "\n\n".join(page.get("text", "") for page in pages)
        }
    return canonical, {"total": elapsed}


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
    parser.add_argument(
        "--remote",
        help="backend base URL, e.g. http://192.168.1.220:8000 (no local models needed)",
    )
    parser.add_argument(
        "--api-token",
        default=os.environ.get("O2J_API_TOKEN"),
        help="X-API-Token for the remote backend",
    )
    parser.add_argument("--doc-class", help="override document class for --remote")
    args = parser.parse_args()

    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")

    if args.remote:
        result, timings = run_remote(
            args.pdf,
            args.remote,
            args.api_token,
            doc_class=args.doc_class,
        )
        out = write_result(args.pdf, result, args.out_dir)
        print(f"[ok] remote backend: {args.remote}")
        print(f"total={timings['total']:.2f}s")
        print(f"wrote {out}")
        return

    os.environ["MLX_MODEL"] = args.ocr_model
    os.environ["OCR_LLM_MODEL"] = args.llm_profile
    os.environ.setdefault("API_KEY", "local-cli")

    base_url = check_servers(Path(args.ocr_model), args.llm_profile)
    print(f"[ok] LLM {args.llm_profile}: {base_url}")
    print(f"[ok] OCR weights: {args.ocr_model}")
    print(f"[i] backend API: {'running' if backend_health() else 'not needed/stopped'}")

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
