# LLM module contract

The OCR services do not contain LLM code. An incoming LLM module plugs in through
one optional environment variable:

```bash
OCR_LLM_PROCESSOR=your_package.your_module:your_processor
```

The value is `import.path:attribute`. The attribute may be either:

- an object with a `process(document)` method, or
- a plain callable accepting `document`.

Nothing is loaded when the variable is unset; the response has no `llm` field.

## Interface

```python
class LLMProcessor:
    def process(self, document: OCRDocument) -> object: ...
```

`OCRDocument` comes from `ocr_common.ports` and is frozen:

```python
@dataclass(frozen=True)
class OCRPage:
    number: int          # 1-based page number
    text: str            # OCR/grounding markdown for that page

@dataclass(frozen=True)
class OCRDocument:
    backend: str         # "cuda" or "mlx"
    model: str           # active OCR model id
    pages: tuple[OCRPage, ...]
```

The return value must be JSON-serializable. It is added verbatim as `response["llm"]`.

## Response shape

Without a processor:

```json
{"backend": "cuda", "pages": [{"page": 1, "text": "..."}]}
```

With a processor:

```json
{"backend": "cuda", "pages": [{"page": 1, "text": "..."}], "llm": <returned value>}
```

## Rules for the incoming module

- Do not import `ocr_api.app` or `local_ai.app`; depend only on `ocr_common.ports`.
- Do not mutate `OCRDocument`; build a new return value.
- Keep inference inside `process()`; the HTTP layer already serializes OCR calls
  with one lock. Coordinate with the owner if the LLM needs its own lock.
- Add the module's dependencies to the `gpu` extra in `pyproject.toml`, not to
  `ocr_common`.
- Startup logs the resolved processor type; `--verbose` shows pipeline timings.
