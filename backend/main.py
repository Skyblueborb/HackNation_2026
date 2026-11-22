"""FastAPI — warstwa HTTP nad magazynami SQLite.

Dane dokumentów nie są nikdy częścią repo ani obrazu Dockera. Wszystkie
ścieżki i token dostępu pochodzą ze zmiennych środowiskowych (patrz
.env.example). API nie ma endpointów zwracających surowy tekst dokumentu.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

from backend.db import repository as repo
from backend.db.connection import db, default_db_path, init_db

REPO_ROOT = Path(__file__).resolve().parents[1]
DocClass = Literal["odwolanie", "pelnomocnictwo", "przelew"]


# ---------------------------------------------------------------------------
# Walidacja kanonicznego JSON-a tym samym modelem Pydantic co w o2jcore
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _canonical_models() -> dict[str, Any]:
    from o2jcore.spec.loader import load_all_classes
    from o2jcore.spec.pydantic_build import build_model

    config_root = Path(os.environ.get("O2J_CONFIG_PATH", str(REPO_ROOT / "configs")))
    specs = load_all_classes(config_root / "classes")
    return {cid: build_model(spec) for cid, spec in specs.items()}


def _validate_canonical(doc_class: str, payload: dict[str, Any]) -> list[str]:
    model = _canonical_models().get(repo.CLASS_TO_SPEC_ID[doc_class])
    if model is None:
        return [f"brak modelu Pydantic dla klasy {doc_class!r}"]
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return []


def _strict_validation() -> bool:
    return os.environ.get("O2J_STRICT_VALIDATION", "0") == "1"


# ---------------------------------------------------------------------------
# Opcjonalny pipeline OCR/LLM — używa go tylko /api/analyze
# ---------------------------------------------------------------------------

OCR_BACKEND = os.environ.get("WEB_OCR_BACKEND", "text")

# "text" reads the PDF's own text layer (pdfplumber) instead of rendering pages
# for a vision model: no GPU, no model weights. Correct for every document in
# the competition set and the default for local development.
_DEFAULT_OCR_MODEL = {
    "text": "pdfplumber",
    "mlx": "local-mlx",
}.get(OCR_BACKEND, "lightonai/LightOnOCR-3-0.8B")
OCR_MODEL = os.environ.get("WEB_OCR_MODEL", _DEFAULT_OCR_MODEL)


@lru_cache(maxsize=1)
def _llm_processor():
    from ocr_common import load_llm_processor

    return load_llm_processor(os.environ.get("OCR_LLM_PROCESSOR"))


def _extractor():
    if OCR_BACKEND == "mlx":
        from local_ai.app import MlxBackend

        return MlxBackend()
    from ocr_api.backends import CudaBackend

    return CudaBackend()


async def _run_remote_ocr(data: bytes, filename: str | None) -> dict:
    """Forward the PDF to an OCR+LLM service on another host."""
    import httpx

    base_url = os.environ.get("OCR_SERVICE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "OCR_SERVICE_URL is required when WEB_OCR_BACKEND=remote"
        )
    api_key = os.environ.get("OCR_SERVICE_KEY", "")
    timeout = float(os.environ.get("OCR_REMOTE_TIMEOUT", "900"))
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        response = await asyncio.to_thread(
            httpx.post,
            f"{base_url}/analyze",
            files={"file": (filename or "upload.pdf", data, "application/pdf")},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"OCR service returned {exc.response.status_code}: {body}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OCR service error: {exc}") from exc
    return response.json()


async def _run_extraction(data: bytes, filename: str | None) -> dict:
    """Dispatch to the text-layer reader, an image backend, or remote OCR.

    `OCR_BACKEND=text` forces the text layer for every upload; the image
    backends still prefer it per-document and OCR only scans. `remote`
    forwards the whole job to another host, which returns pages and the
    optional LLM result.
    """
    if OCR_BACKEND == "remote":
        return await _run_remote_ocr(data, filename)
    if OCR_BACKEND == "text":
        from ocr_common.textlayer import run_textlayer_async

        return await run_textlayer_async(
            data,
            backend=OCR_BACKEND,
            model=OCR_MODEL,
            processor=_llm_processor(),
            filename=filename,
        )

    from ocr_common import run_analyze_async

    return await run_analyze_async(
        data,
        _extractor(),
        backend=OCR_BACKEND,
        model=OCR_MODEL,
        processor=_llm_processor(),
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Autoryzacja (wymagana — wyjątek tylko dla jawnie oznaczonego devu)
# ---------------------------------------------------------------------------


def _ensure_auth_config() -> None:
    """Fail fast: no API token means auth is off, which must be an explicit choice."""
    if os.environ.get("API_TOKEN"):
        return
    if os.environ.get("O2J_DEV_NO_AUTH") == "1":
        return
    raise RuntimeError(
        "API_TOKEN must be set at startup. For local development only, set "
        "O2J_DEV_NO_AUTH=1 to run without auth (never in production)."
    )


def require_token(
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    expected = os.environ.get("API_TOKEN")
    if not expected:
        return
    supplied = x_api_token
    if supplied is None and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied is None or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


# ---------------------------------------------------------------------------
# Modele żądań
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    client_token: str
    client_doc_id: str | None = None  # jeden plik z ZIP-a = jeden dokument
    doc_class: DocClass
    canonical_json: dict[str, Any]
    provenance_json: dict[str, Any] | None = None
    source_name: str | None = None
    pdf_sha256: str | None = None
    text_p1_3: str | None = None
    model_version: str | None = None
    config_version: str | None = None
    reviewer: str | None = None


class CorrectionItemIn(BaseModel):
    field_path: str
    corrected_value: Any = None
    method: str | None = None
    confidence: float | None = None
    page: int | None = None
    bbox: Any = None
    quote: str | None = None


class CorrectionsRequest(BaseModel):
    items: list[CorrectionItemIn]
    reviewer: str | None = None
    model_version: str | None = None
    config_version: str | None = None


# ---------------------------------------------------------------------------
# Aplikacja
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_auth_config()
    if os.environ.get("OCR_LLM_PROCESSOR"):
        from ocr_api.llm_processor import validate_model

        validate_model()
    path = init_db()
    print(f"[o2j] SQLite gotowy: {path}")
    yield


app = FastAPI(title="Odwołania2json API", version="0.1.0", lifespan=lifespan)

_cors_raw = os.environ.get("CORS_ORIGINS", "")
_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or ["http://localhost:3000"]
# Wildcard and credentials are mutually exclusive by spec: never reflect any
# Origin with allow_credentials=True.
_allow_credentials = "*" not in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health nie wymaga tokenu — używa go healthcheck w Dockerze.
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "db": str(default_db_path())}


@app.post("/api/documents/ingest", dependencies=[Depends(require_token)])
def ingest(payload: IngestRequest) -> dict[str, Any]:
    errors = _validate_canonical(payload.doc_class, payload.canonical_json)
    if errors and _strict_validation():
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    with db() as conn:
        result = repo.ingest_document(
            conn,
            client_token=payload.client_token,
            client_doc_id=payload.client_doc_id,
            doc_class=payload.doc_class,
            canonical_json=payload.canonical_json,
            provenance_json=payload.provenance_json,
            source_name=payload.source_name,
            pdf_sha256=payload.pdf_sha256,
            text_p1_3=payload.text_p1_3,
            model_version=payload.model_version,
            config_version=payload.config_version,
            reviewer=payload.reviewer,
        )
    result["validation_errors"] = errors
    return result


# Upload caps live here so a bad body never reaches the OCR/LLM pipeline.
MAX_UPLOAD_BYTES = int(os.environ.get("O2J_MAX_UPLOAD_MB", "25")) * 1024 * 1024
_READ_CHUNK = 1024 * 1024


async def _read_pdf_upload(file: UploadFile) -> bytes:
    """Read at most the cap, then check the PDF magic bytes."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")
    return data


@app.post("/api/analyze", dependencies=[Depends(require_token)])
async def analyze(
    file: UploadFile = File(...),
    client_token: str = Form(...),
    doc_class: DocClass = Form("odwolanie"),
    client_doc_id: str | None = Form(None),
) -> dict[str, Any]:
    """Odczyt tekstu z PDF (warstwa tekstowa albo OCR), opcjonalny LLM i zapis w SQLite."""
    data = await _read_pdf_upload(file)
    result = await _run_extraction(data, file.filename)
    text_p1_3 = "\n\n".join(page["text"] for page in result["pages"])
    llm = result.get("llm")
    if isinstance(llm, dict) and llm.get("rejected"):
        # Document doesn't match any of the three known classes (e.g. a
        # foreign/negative PDF) -- empty result, not a guessed extraction.
        canonical: dict[str, Any] = {}
    elif isinstance(llm, dict) and isinstance(llm.get("data"), dict):
        canonical = llm["data"]
    else:
        canonical = {"raw_text": text_p1_3}
    # LLM returns spec ids (e.g. potwierdzenie_przelewu); storage uses doc
    # classes (przelew). Trust the classified class over the multipart guess.
    if isinstance(llm, dict) and llm.get("class"):
        spec_id = llm["class"]
        for doc_key, mapped_id in repo.CLASS_TO_SPEC_ID.items():
            if mapped_id == spec_id:
                doc_class = doc_key  # type: ignore[assignment]
                break
    with db() as conn:
        saved = repo.ingest_document(
            conn,
            client_token=client_token,
            client_doc_id=client_doc_id,
            doc_class=doc_class,
            canonical_json=canonical,
            provenance_json={"ocr": OCR_BACKEND, "model": OCR_MODEL},
            source_name=file.filename,
            pdf_sha256=hashlib.sha256(data).hexdigest(),
            text_p1_3=text_p1_3,
        )
    return {**result, **saved, "canonical_json": canonical}


@app.get("/api/documents", dependencies=[Depends(require_token)])
def list_documents(
    job_id: str | None = Query(default=None),
    doc_class: DocClass | None = Query(default=None),
    client_token: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with db() as conn:
        return repo.list_effective_results(
            conn, job_id=job_id, doc_class=doc_class, client_token=client_token
        )


@app.get("/api/documents/{document_id}", dependencies=[Depends(require_token)])
def get_document(document_id: str) -> dict[str, Any]:
    with db() as conn:
        result = repo.get_effective_result(conn, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@app.patch("/api/documents/{document_id}/corrections", dependencies=[Depends(require_token)])
def add_corrections(document_id: str, payload: CorrectionsRequest) -> dict[str, Any]:
    with db() as conn:
        try:
            session_id = repo.save_corrections(
                conn,
                document_id=document_id,
                items=[i.model_dump() for i in payload.items],
                reviewer=payload.reviewer,
                model_version=payload.model_version,
                config_version=payload.config_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"document_id": document_id, "correction_session_id": session_id}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str) -> dict[str, Any]:
    with db() as conn:
        job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
