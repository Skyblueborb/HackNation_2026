# OCR LLM Serving Path Implementation Plan

> **ARCHIVED 2026-11-21 — DO NOT EXECUTE.** Historical plan only. It describes
> files and flags that no longer exist (`src/lab/serve.py`,
> `scripts/make-llama-model.sh`, root `Dockerfile`, `OCR_BACKEND`, llama.cpp/
> GGUF OCR). Current services are `ocr-api` (CUDA) and `local-ai` (MLX); see
> `docs/BACKEND.md`, `docs/llm-runtime.md` and `configs/models.yaml`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One FastAPI server exposing scanned-PDF OCR through `lightonai/LightOnOCR-3-4B` in full BF16, with `mlx` and `llama_cpp` backends sharing `extract_page(image)`.

**Architecture:** `src/lab/serve.py` holds the API key check, PDF-to-image rendering, one inference lock, and two lazy-loaded backend implementations selected by `OCR_BACKEND`. mlx-vlm loads the HF repo directly; the llama_cpp backend calls a separate CPU-only `llama-server` over its OpenAI-compatible API. No other model, no quantized weights, no PDF text-layer path.

**Tech Stack:** FastAPI, uvicorn, pypdfium2, Pillow, mlx-vlm (macOS only), `openai` client, llama.cpp `llama-server`, pytest + httpx.

**Spec:** `docs/superpowers/specs/2026-11-21-ocr-backends-design.md`

## Global Constraints

- Model id is exactly `lightonai/LightOnOCR-3-4B` on both backends.
- Full BF16 weights only. No quantized checkpoints and no `subfolder=` 4bit/8bit.
- No PDF text extraction, no PyMuPDF, no `fitz`. Scanned PDFs only.
- Transcription prompt is the empty string `""`; `"grounding"` is not used.
- Inference is serialized by one module-level `asyncio.Lock()`.
- Uvicorn runs with `--workers 1`.
- CPU path uses published F16 mmproj plus a locally converted BF16 GGUF; the converter is `convert_hf_to_gguf.py --outtype bf16`.

## Review Focus

- Empty prompt must produce markdown transcription, not grounding coordinates — pinned by `test_extract_page_uses_empty_prompt` in Task 2.
- mlx `generate` must receive `[PIL.Image.Image]`, not a file path — pinned by `test_mlx_backend_passes_pil_image` in Task 2.
- llama-server without mmproj rejects image requests — documented in Task 4; no unit test (external process).
- Two simultaneous `/analyze` calls must not overlap — pinned by `test_inference_is_serialized` in Task 3.
- Missing or wrong `X-API-Key` must not reach inference — pinned by `test_analyze_requires_key` and `test_analyze_rejects_wrong_key` in Task 3.

---

### Task 1: Dependencies, licenses, and CPU model conversion docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `uv.lock`
- Modify: `docs/LICENSES.md`
- Create: `scripts/make-llama-model.sh`

**Interfaces:**
- Produces: extras `serve` (fastapi, uvicorn, python-multipart, httpx) and `demo` (mlx-vlm); `scripts/make-llama-model.sh` writes a BF16 GGUF + F16 mmproj into `models/`.

- [ ] **Step 1: Add optional dependency groups in `pyproject.toml`**

Under `[project.optional-dependencies]`, add:

```toml
serve = ["fastapi", "uvicorn", "python-multipart", "httpx"]
demo = ["mlx-vlm"]
```

Keep all existing groups unchanged.

- [ ] **Step 2: Regenerate lock files**

Run: `uv lock && uv export --no-dev --extra serve --extra demo --format requirements-txt > requirements.txt`
Expected: command succeeds; `requirements.txt` contains `fastapi`, `uvicorn`, `mlx-vlm`.

- [ ] **Step 3: Add license rows**

Append to `docs/LICENSES.md` table: FastAPI (MIT), uvicorn (BSD-3), mlx-vlm (MIT), python-multipart (Apache-2.0), LightOnOCR-3-4B (Apache-2.0). Use the existing table columns.

- [ ] **Step 4: Write BF16 GGUF conversion script**

Create `scripts/make-llama-model.sh` that: downloads `lightonai/LightOnOCR-3-4B` via `huggingface-cli download`, runs `python llama.cpp/convert_hf_to_gguf.py models/LightOnOCR-3-4B --outfile models/LightOnOCR-3-4B-BF16.gguf --outtype bf16`, and downloads `mmproj-LightOnOCR-3-4B-F16.gguf` from `richardyoung/LightOnOCR-3-4B-GGUF`. Print the resulting paths. No quantized output.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt uv.lock docs/LICENSES.md scripts/make-llama-model.sh
git commit -m "feat: add OCR serving dependencies and BF16 GGUF conversion"
```

---

### Task 2: Backend interface and PDF rendering

**Files:**
- Create: `src/lab/serve.py`
- Test: `tests/test_serve.py`

**Interfaces:**
- Consumes: `OCR_MAX_TOKENS` env (default `2048`), `LLAMA_CPP_BASE_URL` (default `http://localhost:8080/v1`), `LLAMA_CPP_MODEL` (default `LightOnOCR-3-4B-BF16`).
- Produces: `MODEL_ID: str`, `render_pages(data: bytes, dpi: int = 300) -> list[Image.Image]`, `extract_page(image: Image.Image) -> str`, `get_backend()` returning an object with `extract_page`, `MlxBackend`, `LlamaCppBackend`.

- [ ] **Step 1: Write failing tests**

```python
def test_render_pages_returns_one_image_per_page():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    pages = render_pages(buf.getvalue())
    assert len(pages) == 1
    assert isinstance(pages[0], Image.Image)


def test_extract_page_uses_empty_prompt(monkeypatch):
    seen = {}
    def fake_apply(processor, config, prompt, num_images):
        seen["prompt"] = prompt
        return "formatted"
    monkeypatch.setattr(serve, "apply_chat_template", fake_apply)
    monkeypatch.setattr(serve, "mlx_session", lambda: (object(), object(), object()))
    monkeypatch.setattr(serve, "generate", lambda *a, **k: SimpleNamespace(text="text"))
    assert MlxBackend().extract_page(Image.new("RGB", (8, 8))) == "text"
    assert seen["prompt"] == ""


def test_mlx_backend_passes_pil_image(monkeypatch):
    image = Image.new("RGB", (8, 8))
    monkeypatch.setattr(serve, "mlx_session", lambda: (object(), object(), object()))
    monkeypatch.setattr(serve, "apply_chat_template", lambda *a, **k: "formatted")
    def fake_generate(model, processor, prompt, image=None, **k):
        assert isinstance(image[0], Image.Image)
        return SimpleNamespace(text="ok")
    monkeypatch.setattr(serve, "generate", fake_generate)
    MlxBackend().extract_page(image)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_serve.py -v`
Expected: FAIL on import of `render_pages` from `lab.serve`.

- [ ] **Step 3: Implement backend module**

In `src/lab/serve.py`:
- Define `MODEL_ID = "lightonai/LightOnOCR-3-4B"`, `BACKEND = os.environ.get("OCR_BACKEND", "mlx")`, `MAX_TOKENS = int(os.environ.get("OCR_MAX_TOKENS", "2048"))`.
- `render_pages(data: bytes, dpi: int = 300) -> list[Image.Image]` uses `pypdfium2.PdfDocument(data)` and `page.render(scale=dpi / 72).to_pil()`.
- `mlx_session()` lazily loads `(model, processor, config)` once via `mlx_vlm.load(MODEL_ID)` and `mlx_vlm.utils.load_config(MODEL_ID)`; no `subfolder` argument.
- `MlxBackend.extract_page(image)` formats the empty prompt with `apply_chat_template(processor, config, "", num_images=1)` and calls `generate(model, processor, formatted, image=[image], max_tokens=MAX_TOKENS, temperature=0.0)`, returning `str(result.text).strip()`.
- `LlamaCppBackend.extract_page(image)` encodes the image as a PNG data URI and POSTs it through the `openai` client to `LLAMA_CPP_BASE_URL` with model `LLAMA_CPP_MODEL`, `max_tokens=MAX_TOKENS`, `temperature=0`, returning `response.choices[0].message.content.strip()`.
- `get_backend()` returns one cached instance chosen by `BACKEND`; raise `ValueError` for unknown values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_serve.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lab/serve.py tests/test_serve.py
git commit -m "feat: add OCR backend interface and PDF rendering"
```

---

### Task 3: FastAPI app with key auth and serialized inference

**Files:**
- Modify: `src/lab/serve.py`
- Modify: `tests/test_serve.py`

**Interfaces:**
- Consumes: `render_pages`, `get_backend`, `BACKEND`, `MODEL_ID` from Task 2.
- Produces: `app` (FastAPI), `inference_lock: asyncio.Lock`, `verify_key(x_api_key: str = Header(...))`, `POST /analyze`, `GET /health`.

- [ ] **Step 1: Write failing tests**

```python
def test_analyze_requires_key():
    r = TestClient(app).post("/analyze", files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code in (401, 422)


def test_analyze_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setattr(serve, "API_KEY", "secret")
    r = TestClient(app).post("/analyze", headers={"X-API-Key": "wrong"},
                            files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 401


def test_analyze_returns_pages(monkeypatch):
    calls = []
    class B:
        def extract_page(self, image):
            calls.append(image)
            return "  ocr  "
    monkeypatch.setattr(serve, "get_backend", lambda: B())
    r = TestClient(app).post("/analyze", headers={"X-API-Key": serve.API_KEY},
                            files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 200
    assert r.json()["pages"] == [{"page": 1, "text": "ocr"}]
    assert len(calls) == 1


def test_inference_is_serialized(monkeypatch):
    active = 0
    peak = 0
    class B:
        def extract_page(self, image):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.02)
            active -= 1
            return "x"
    monkeypatch.setattr(serve, "get_backend", lambda: B())
    async def run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await asyncio.gather(*[
                client.post("/analyze", headers={"X-API-Key": serve.API_KEY},
                            files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})
                for _ in range(2)
            ])
    asyncio.run(run())
    assert peak == 1
```

Add helpers `pdf_bytes()` building a one-page PDF with Pillow and imports `asyncio`, `time`, `httpx`, `fastapi.testclient`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_serve.py -v`
Expected: FAIL on missing `app` / `inference_lock`.

- [ ] **Step 3: Implement the API**

In `src/lab/serve.py`:
- `API_KEY = os.environ.get("API_KEY", "dev-key")`, `inference_lock = asyncio.Lock()`.
- `verify_key(x_api_key: str = Header(...))` calls `secrets.compare_digest(x_api_key, API_KEY)` and raises `HTTPException(401, "Invalid API key")` on mismatch.
- `GET /health` returns `{"backend": BACKEND, "model": MODEL_ID}` with no auth.
- `POST /analyze` has `dependencies=[Depends(verify_key)]`, takes `file: UploadFile = File(...)`, reads bytes, renders pages, and for each page awaits `asyncio.to_thread(backend.extract_page, image)` **inside one `async with inference_lock`** covering the whole document.
- Response shape: `{"backend": BACKEND, "pages": [{"page": n, "text": text}]}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_serve.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lab/serve.py tests/test_serve.py
git commit -m "feat: add authenticated OCR analyze endpoint"
```

---

### Task 4: CPU Dockerfile and run instructions

**Files:**
- Create: `Dockerfile`
- Modify: `README.md`

**Interfaces:**
- Consumes: `src/lab/serve.py`, `pyproject.toml` extras.

- [ ] **Step 1: Write CPU Dockerfile**

`FROM python:3.13-slim`, copy project, `pip install -e .[serve]`, set `ENV OCR_BACKEND=llama_cpp`, `EXPOSE 8000`, entrypoint `uvicorn lab.serve:app --host 0.0.0.0 --port 8000 --workers 1`. Do not install mlx-vlm in the image.

- [ ] **Step 2: Document both runs in README**

Add commands:
- Mac demo: `uv sync --extra demo --extra serve && API_KEY=<key> uvicorn lab.serve:app --workers 1`; start with `OCR_BACKEND=mlx`.
- CPU: run `bash scripts/make-llama-model.sh`; start `llama-server -m models/LightOnOCR-3-4B-BF16.gguf --mmproj models/mmproj-LightOnOCR-3-4B-F16.gguf -ngl 0 -c 8192 --host 0.0.0.0 --port 8080`; then `OCR_BACKEND=llama_cpp ... uvicorn ...`.
- Network: `cloudflared tunnel --url http://localhost:8000`; give judges the `https://*.trycloudflare.com` URL and `X-API-Key`.
- Keep Mac awake: `caffeinate -dims`.
- Note that mlx-vlm is macOS/Apple-silicon only and the Dockerfile is the CPU target.

- [ ] **Step 3: Verify API and docs locally**

Run: `pytest tests/test_serve.py -v && python -c "import lab.serve; print(lab.serve.app.title)"`
Expected: all tests pass; prints a title.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile README.md
git commit -m "feat: add CPU Dockerfile and OCR serving instructions"
```

---

### Task 5: Full verification

**Files:** none

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including pre-existing tests.

- [ ] **Step 2: Verify app boots in both backend modes**

Run: `OCR_BACKEND=llama_cpp python -c "import lab.serve; print(lab.serve.get_backend().__class__.__name__)"`
Expected: `LlamaCppBackend`.

Run: `OCR_BACKEND=mlx python -c "import lab.serve; print(lab.serve.get_backend().__class__.__name__)"`
Expected: `MlxBackend` (on Apple Silicon with `demo` extra installed).

- [ ] **Step 3: Verify dependency tree**

Run: `uv sync --extra demo --extra serve`
Expected: succeeds on macOS; mlx-vlm absent in Docker CPU image.

- [ ] **Step 4: Commit any fixes**

```bash
git status --short
```
Expected: clean working tree.
