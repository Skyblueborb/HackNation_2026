# OpenCode prompt — review fixes (backend / OCR services)

Temporary working file. `work/` is gitignored, so this is never committed.
Source: code review of commits `c431460`, `07acc0b`, `a013093` (backend + OCR
services), plus one prompt-quality bug found while testing the wired-up flow.

Paste everything between the markers into OpenCode.

---8<--- PROMPT START ---8<---

Context: lab + production repo for Odwołania2json (JSON extraction from KIO/UZP PDFs).
These 6 items come from a code review of the backend/OCR-services code. Apply them
one at a time, each as its own commit, running `uv run pytest -q` after each to keep
the suite green (currently 264/264, plus whatever tests you add).

IMPORTANT — do not conflict with work already done:
`docker-compose.yml`, `.env.example`, `scripts/dev-up.sh` and
`src/ocr_common/textlayer.py` were just added, and `backend/main.py`,
`backend/requirements.txt` and `docs/BACKEND.md` were just modified to add a
`WEB_OCR_BACKEND=text` path (reads the PDF text layer via pdfplumber, no GPU).
Build on those files; do not recreate or revert them.

### 1. Fix correction sessions discarding earlier fixes (backend/db/repository.py)
`save_corrections()` builds `corrected` from the IMMUTABLE original model output
(`result["canonical_json"]`) on every call. Since `get_effective_result()` returns
only the newest session's `corrected_json`, a second correction session silently
reverts every field fixed by an earlier one.

Reproduced: ingest a document, PATCH /api/documents/{id}/corrections to fix
`Odwolujacy[0].nazwa`, then PATCH again to fix `Odwolujacy[0].nip`. The effective
JSON then shows the fixed `nip` but `nazwa` has snapped back to the model's
original wrong value.

- Base each new correction session on the CURRENT effective JSON (latest session's
  `corrected_json` when one exists), not on the pristine model output. Keep
  `predicted_json` semantics intact: stores 1-3 must stay immutable and
  `get_effective_result()["predicted_json"]` must keep returning the original
  model output so clean F1 stays measurable.
- Decide and document what `correction_items.predicted_value` means for a second
  session on the same field (previous corrected value vs. original prediction) —
  `export_training_pairs()` consumes these, so make it deliberate.
- Add a regression test: two sequential `save_corrections()` calls on two different
  fields of one document; assert the effective JSON contains BOTH fixes.

### 2. Fix the CORS wildcard-with-credentials hole (backend/main.py)
`allow_origins=_origins or ["*"]` together with `allow_credentials=True` makes
Starlette reflect ANY Origin header back with `Access-Control-Allow-Credentials:
true` (verified against the installed Starlette 1.10). When `CORS_ORIGINS` resolves
empty and `API_TOKEN` is unset (the documented local-dev default = no auth at all),
any website the user visits can read and write every stored document cross-origin.

- Never fall back to `"*"`. Either fail fast at startup with a clear error when
  `CORS_ORIGINS` is empty, or default to an explicit `http://localhost:3000`.
- If a wildcard is ever genuinely wanted, it must come with
  `allow_credentials=False`; the two are mutually exclusive by spec.
- Add a test asserting a disallowed Origin does NOT get reflected.

### 3. Make API_KEY lazy instead of import-time (src/ocr_common/common.py)
`API_KEY = os.environ.get("API_KEY")` plus a module-level
`raise RuntimeError("API_KEY must be set")` runs on import. Because
`backend/main.py` imports `ocr_common` lazily inside the request handler, a
missing API_KEY surfaces as an unhandled 500 on the first `/api/analyze` call
rather than a startup error — and the backend's own auth is `API_TOKEN`, so it
shouldn't need the OCR services' key at all just to read a PDF text layer.

- Resolve the key inside `verify_key()` (keep `secrets.compare_digest`), raising a
  clear error only when a request actually needs it.
- Keep the fail-fast guarantee for the standalone OCR services (`ocr-api serve`,
  `local-ai serve`) — check at app startup/lifespan there, not at module import.
- Add a test: importing `ocr_common` with no API_KEY set must not raise.

### 4. Use a timing-safe token comparison (backend/main.py)
`require_token()` uses `supplied != expected`, which short-circuits on the first
mismatched byte and leaks a correct-prefix timing signal. The correct pattern
already exists one module over in `src/ocr_common/common.py` (`secrets.compare_digest`).
- Switch to `secrets.compare_digest`, guarding the None case first.

### 5. Construct the LLM processor lazily (src/ocr_api/llm_processor.py)
`processor = LabLLMProcessor()` at module scope validates `OCR_LLM_MODEL` and loads
`configs/models.yaml` at import time, so a bad profile name crashes on the first
analyze request instead of at a clear startup check.
- Expose a lazily-initialised processor (module-level `__getattr__`, or a
  `get_processor()` factory the registry resolves) so `ocr_common.load_llm_processor`
  still works with `OCR_LLM_PROCESSOR=ocr_api.llm_processor:processor`.
- Validate `OCR_LLM_MODEL` at app startup and fail with a message naming the
  unknown profile and the available keys from configs/models.yaml.

### 6. Fix the swapped-account-numbers prompt bug (configs/prompts/extract_potwierdzenie_przelewu.j2)
Observed live against real data: qwen3-4b on `przyklad_01` returned
`na_rachunek` and `z_rachunku` SWAPPED (4/6 fields correct). The source PDF labels
them "Rachunek obciążany" (debited = `z_rachunku`) and "Rachunek odbiorcy"
(recipient = `na_rachunek`), which the prompt does not currently disambiguate.
- Spell out the mapping in the prompt: `z_rachunku` = payer's/debited account
  ("Rachunek obciążany", under "Płatnik"); `na_rachunek` = recipient's account
  ("Rachunek odbiorcy", under "Adresat przelewu").
- Verify against gold:
    uv run lab serve --model local-llm        # terminal 1
    uv run lab predict-one --set przyklad_01 --class potwierdzenie_przelewu --model local-llm
  compared with dane/przyklad_01/przelew.json — all 6 fields must match.
- Then run a real measurement over the dev split and report F1:
    uv run lab run --model local-llm --experiment configs/experiments/E0_baseline.yaml

After all 6 steps run `uv run pytest -q` and paste the result. Do not change
evaluator behaviour (src/lab/eval/*) — out of scope.

---8<--- PROMPT END ---8<---
