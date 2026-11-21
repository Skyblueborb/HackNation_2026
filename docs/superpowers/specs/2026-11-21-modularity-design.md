# Modularity design — OCR services

## Intent

Make the codebase accept an incoming LLM module without writing LLM code here.

## Decisions

- `ocr_common/ports.py` owns frozen data types (`OCRPage`, `OCRDocument`) and
  protocols (`PageExtractor`, `LLMProcessor`). All modules depend on it.
- `ocr_common/pipeline.py` owns rendering, locking, OCR calls, logging, and the
  optional processor call. Both HTTP apps delegate to `run_ocr_async`.
- `ocr_common/registry.py` resolves `OCR_LLM_PROCESSOR=module:attribute` to an
  object with `process()` or a callable. No LLM implementation lives here.
- OCR engines stay in `ocr_api/backends.py` and `local_ai/app.py`; each exposes
  `extract_page(image)`.
- HTTP apps contain only config, endpoints, and backend construction.

## Compatibility

Response stays `{"backend", "pages"}` when no processor is configured. With a
processor, an extra `llm` field is added. API key and `/health` unchanged.

## Files touched

`src/ocr_common/{__init__,common,ports,pipeline,registry}.py`,
`src/ocr_api/app.py`, `src/local_ai/app.py`, `docs/llm-module-contract.md`,
`tests/test_pipeline.py`.

## Left to coworker

Implement `LLMProcessor` in their own package and set `OCR_LLM_PROCESSOR`.
