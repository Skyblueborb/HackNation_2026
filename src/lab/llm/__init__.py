"""OCR -> LLM -> JSON pipeline components.

The document-class schemas in configs/classes/*.yaml remain the single source
of truth: build_json_schema() supplies constrained decoding, build_model()
supplies validation and normalization.
"""
