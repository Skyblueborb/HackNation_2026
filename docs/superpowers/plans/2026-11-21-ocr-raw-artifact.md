# Raw OCR Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--save-ocr` to `ocr-pdf2json` so raw per-page OCR text is saved for debugging.

**Architecture:** `run_document` and `run_remote` return the per-page texts alongside the canonical result. A new `write_ocr_text` helper writes `<stem>.ocr.txt` with `--- page N ---` markers; `main()` calls it only when the flag is set. No backend, schema or UI change.

**Tech Stack:** Python 3.13, pytest, existing `ocr_api.pdf_to_json` CLI.

**Spec:** `docs/superpowers/specs/2026-11-21-ocr-raw-artifact-design.md`

## Global Constraints

- Artifact filename is exactly `<pdf-stem>.ocr.txt` in `--out-dir`.
- Section header is exactly `--- page N ---` with 1-based page numbers.
- Text is written verbatim; an empty page still gets its header.
- Works in local MLX mode and in `--remote` mode.
- Canonical JSON output stays unchanged.

## Review Focus

- Empty page text — page header must still appear; pinned by `test_write_ocr_text_writes_pages_verbatim`.
- No flag — no artifact created; pinned by `test_main_without_flag_does_not_write_ocr`.
- Remote mode — texts come from response `pages`; pinned by `test_run_remote_returns_texts`.
- Missing `--out-dir` — created on demand; pinned by `test_write_ocr_text_writes_pages_verbatim` using a nested path.
- Non-ASCII and leading/trailing whitespace — preserved byte-for-byte; pinned by `test_write_ocr_text_writes_pages_verbatim`.

---

### Task 1: Save raw OCR text artifact

**Files:**
- Modify: `src/ocr_api/pdf_to_json.py`
- Modify: `tests/test_pdf_to_json.py`
- Modify: `docs/CLI.md`

**Interfaces:**
- Consumes: `run_document(data, filename, model_id)` and `run_remote(pdf, base_url, token, ...)`, existing signatures.
- Produces:
  - `write_ocr_text(pdf: Path, texts: list[str], out_dir: Path) -> Path`
  - `run_document(...) -> tuple[dict[str, Any], dict[str, float], list[str]]`
  - `run_remote(...) -> tuple[dict[str, Any], dict[str, float], list[str]]`
  - CLI flag `--save-ocr` (`store_true`)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pdf_to_json.py`:

```python
def test_write_ocr_text_writes_pages_verbatim(tmp_path):
    out = tmp_path / "nested" / "out"
    path = tool.write_ocr_text(
        tmp_path / "odwolanie.pdf", ["  strona 1  ", ""], out
    )
    assert path.name == "odwolanie.ocr.txt"
    assert path.read_text(encoding="utf-8") == (
        "--- page 1 ---\n\n  strona 1  \n\n--- page 2 ---\n\n"
    )
```

Update existing `test_run_document_returns_result_and_timings` to unpack three values and assert `texts == ["OCR TEXT"]`.

Update existing `test_run_remote_uses_api_response` so the fake response has `pages: [{"text": "A"}, {"text": "B"}]`, unpack three values, and assert `texts == ["A", "B"]`.

Add:

```python
def test_main_saves_ocr_when_flag_set(monkeypatch, tmp_path):
    pdf = tmp_path / "odwolanie.pdf"
    pdf.write_bytes(b"%PDF")
    out = tmp_path / "out"
    monkeypatch.setattr(tool, "check_servers", lambda *a: "http://llm")
    monkeypatch.setattr(tool, "backend_health", lambda: False)
    monkeypatch.setattr(
        tool,
        "run_document",
        lambda *a: ({"ok": 1}, {"render": 0.0, "ocr": 0.0, "llm": 0.0, "total": 0.0}, ["RAW"]),
    )
    monkeypatch.setattr(tool, "write_result", lambda *a: out / "odwolanie.json")
    monkeypatch.setattr(
        tool.sys,
        "argv",
        ["ocr-pdf2json", str(pdf), "--out-dir", str(out), "--save-ocr"],
    )
    tool.main()
    assert (out / "odwolanie.ocr.txt").read_text(encoding="utf-8") == (
        "--- page 1 ---\n\nRAW\n\n"
    )


def test_main_without_flag_does_not_write_ocr(monkeypatch, tmp_path):
    pdf = tmp_path / "odwolanie.pdf"
    pdf.write_bytes(b"%PDF")
    out = tmp_path / "out"
    monkeypatch.setattr(tool, "check_servers", lambda *a: "http://llm")
    monkeypatch.setattr(tool, "backend_health", lambda: False)
    monkeypatch.setattr(
        tool,
        "run_document",
        lambda *a: ({"ok": 1}, {"render": 0.0, "ocr": 0.0, "llm": 0.0, "total": 0.0}, ["RAW"]),
    )
    monkeypatch.setattr(tool, "write_result", lambda *a: out / "odwolanie.json")
    monkeypatch.setattr(
        tool.sys, "argv", ["ocr-pdf2json", str(pdf), "--out-dir", str(out)]
    )
    tool.main()
    assert not (out / "odwolanie.ocr.txt").exists()
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest -q tests/test_pdf_to_json.py -v`
Expected: FAIL on `write_ocr_text` missing and on the changed return arity.

- [ ] **Step 3: Implement artifact writing**

In `src/ocr_api/pdf_to_json.py`:
- Add `write_ocr_text(pdf: Path, texts: list[str], out_dir: Path) -> Path` that creates `out_dir` and writes `"".join(f"--- page {i} ---\n\n{text}\n\n" for i, text in enumerate(texts, 1))` as UTF-8.
- Change `run_document` to return `(result, timings, texts)`.
- Change `run_remote` to return `(result, timings, [page.get("text", "") for page in response.get("pages", [])])`.
- Add `--save-ocr` with `action="store_true"`.
- In `main()`, after `write_result(...)`, call `write_ocr_text(...)` when the flag is set and print the path, in both remote and local branches.

- [ ] **Step 4: Document the flag**

Add `--save-ocr` to the options block in `docs/CLI.md` and one line describing `<stem>.ocr.txt`.

- [ ] **Step 5: Verify tests pass**

Run: `uv run pytest -q tests/test_pdf_to_json.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 6: Commit**

```bash
git add src/ocr_api/pdf_to_json.py tests/test_pdf_to_json.py docs/CLI.md \
  docs/superpowers/specs/2026-11-21-ocr-raw-artifact-design.md \
  docs/superpowers/plans/2026-11-21-ocr-raw-artifact.md
git commit -m "feat(cli): save raw OCR text with --save-ocr"
```
