# Design: raw OCR artifact in `ocr-pdf2json` (2026-11-21)

## Intent

Add a CLI flag that saves the raw per-page OCR text next to the canonical JSON.
Use case: debugging OCR visually, e.g. an empty page or a degenerate model
output. The artifact is for humans, not for machine re-ingestion.

## Goals

- `--save-ocr` writes `<pdf-stem>.ocr.txt` into `--out-dir`.
- Sections are separated with `--- page N ---` headers.
- Text is preserved verbatim, including empty pages.
- Works in local MLX mode and in `--remote` mode (backend returns `pages`).

## Non-goals

- No change to the canonical JSON schema or to the backend response.
- No new dependency, no config knob, no UI change.
- No second artifact format.

## Decisions

- Chosen: plain text file. Best for terminal inspection, smallest change.
- Rejected: JSON with `pages[]` — worse for eyeballing, more code.
- Rejected: `_ocr` key in canonical JSON — mixes intermediate and final output.

## Approach

- `run_document` and `run_remote` return `(result, timings, texts)`.
- `write_ocr_text(pdf, texts, out_dir)` writes the text artifact.
- `main()` calls it when `--save-ocr` is set and prints the path.
- One unit test covers file name, page markers and verbatim text.

## Risks

- Remote mode can only save text the backend chose to return; it is not the
  raw model output from the remote host.
