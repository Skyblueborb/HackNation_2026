"""CLI: every PDF under input/ -> canonical JSON under output/, same tree.

This is the entry point the graders run (see `RUN.md`): it must process an
unseen set of documents unattended and exit on its own. It reuses the exact
pipeline `/api/analyze` uses (`run_textlayer_async` + the lab LLM processor),
so batch output and the GUI cannot drift apart.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

from ocr_common import load_llm_processor
from ocr_common.textlayer import run_textlayer_async

DEFAULT_PROCESSOR = "ocr_api.llm_processor:processor"
# Matches the backend's remote-OCR timeout: one long document must not be cut off.
REMOTE_TIMEOUT = float(os.environ.get("OCR_REMOTE_TIMEOUT", "900"))


def result_json(response: dict[str, Any]) -> dict[str, Any]:
    """Canonical extraction, or `{}` when the document matches no known class.

    An empty JSON is the expected answer for negative documents, so a rejected
    classification and a failed extraction produce the same file. Guessing a
    class would cost more F1 than staying silent.
    """
    llm = response.get("llm")
    if not isinstance(llm, dict) or llm.get("rejected"):
        return {}
    data = llm.get("data")
    return data if isinstance(data, dict) else {}


def llm_error(response: dict[str, Any]) -> str | None:
    """Error reported by the processor: LLM unreachable, unparsable JSON, ...

    Reported separately from a rejected classification, which is a legitimate
    empty result. Without this, an LLM that is down looks like a document set
    full of negatives.
    """
    llm = response.get("llm")
    return llm.get("error") if isinstance(llm, dict) else None


def pdfs_under(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def process(pdf: Path, processor: Any) -> dict[str, Any]:
    return asyncio.run(
        run_textlayer_async(pdf.read_bytes(), processor=processor, filename=pdf.name)
    )


def process_remote(pdf: Path, base_url: str, api_key: str) -> dict[str, Any]:
    """Send the PDF to `ocr-api serve` on the GPU box and reuse its response.

    `ocr_api` runs the same pipeline there, so the reply has the same `pages` /
    `llm` shape as the local path and needs no separate result handling.
    """
    import httpx

    with pdf.open("rb") as handle:
        response = httpx.post(
            f"{base_url.rstrip('/')}/analyze",
            files={"file": (pdf.name, handle, "application/pdf")},
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=REMOTE_TIMEOUT,
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(prog="ocr-batch")
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument(
        "--service",
        default=os.environ.get("OCR_SERVICE_URL", ""),
        help="base URL of `ocr-api serve` on the GPU box; empty = run locally",
    )
    parser.add_argument("--service-key", default=os.environ.get("OCR_SERVICE_KEY", ""))
    args = parser.parse_args()

    if not args.input.is_dir():
        raise SystemExit(f"input directory not found: {args.input}")

    pdfs = pdfs_under(args.input)
    if not pdfs:
        print(f"[warn] no PDF found under {args.input}", file=sys.stderr)
        return

    if args.service:
        run = partial(process_remote, base_url=args.service, api_key=args.service_key)
        print(f"[ok] {len(pdfs)} PDF(s) via {args.service}")
    else:
        processor = load_llm_processor(
            os.environ.get("OCR_LLM_PROCESSOR") or DEFAULT_PROCESSOR
        )
        run = partial(process, processor=processor)
        print(
            f"[ok] {len(pdfs)} PDF(s) locally, "
            f"model={os.environ.get('OCR_LLM_MODEL', 'default')}"
        )

    failures = 0
    started = time.perf_counter()
    for index, pdf in enumerate(pdfs, 1):
        relative = pdf.relative_to(args.input).with_suffix(".json")
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        try:
            response = run(pdf)
        except Exception as exc:  # one bad document must not stop the run
            print(f"[fail] {relative}: {exc}", file=sys.stderr)
            data = {}
            failures += 1
        else:
            data = result_json(response)
            error = llm_error(response)
            if error:
                print(f"[fail] {relative}: {error}", file=sys.stderr)
                failures += 1
        destination.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        state = "empty" if not data else f"{len(data)} fields"
        print(f"[{index}/{len(pdfs)}] {relative} {state} {time.perf_counter() - t0:.1f}s")

    print(
        f"[done] {len(pdfs)} file(s), {failures} failure(s), "
        f"{time.perf_counter() - started:.1f}s total"
    )


if __name__ == "__main__":
    main()
