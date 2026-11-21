"""FastAPI — warstwa HTTP nad magazynami SQLite.

Dane dokumentów nie są nikdy częścią repo ani obrazu Dockera. Wszystkie
ścieżki i token dostępu pochodzą ze zmiennych środowiskowych (patrz
.env.example). API nie ma endpointów zwracających surowy tekst dokumentu.
"""

from __future__ import annotations

import hashlib
import os
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

OCR_BACKEND = os.environ.get("WEB_OCR_BACKEND", "cuda")
OCR_MODEL = os.environ.get(
    "WEB_OCR_MODEL", "local-mlx" if OCR_BACKEND == "mlx" else "lightonai/LightOnOCR-3-4B"
)


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


# ---------------------------------------------------------------------------
# Autoryzacja (opcjonalna — włącza się przez API_TOKEN)
# ---------------------------------------------------------------------------


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
    if supplied != expected:
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
    path = init_db()
    print(f"[o2j] SQLite gotowy: {path}")
    yield


app = FastAPI(title="Odwołania2json API", version="0.1.0", lifespan=lifespan)

_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
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


@app.post("/api/analyze", dependencies=[Depends(require_token)])
async def analyze(
    file: UploadFile = File(...),
    client_token: str = Form(...),
    doc_class: DocClass = Form("odwolanie"),
    client_doc_id: str | None = Form(None),
) -> dict[str, Any]:
    """OCR skanu PDF, opcjonalny LLM i zapis wyniku w SQLite."""
    from ocr_common import run_ocr_async

    data = await file.read()
    result = await run_ocr_async(
        data,
        _extractor(),
        backend=OCR_BACKEND,
        model=OCR_MODEL,
        processor=_llm_processor(),
        filename=file.filename,
    )
    text_p1_3 = "\n\n".join(page["text"] for page in result["pages"])
    llm = result.get("llm")
    canonical = (
        llm["data"]
        if isinstance(llm, dict) and isinstance(llm.get("data"), dict)
        else {"raw_text": text_p1_3}
    )
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
