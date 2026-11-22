"""CUDA backend for lightonai/LightOnOCR-3-4B in full BF16."""

from __future__ import annotations

import os

from PIL import Image

MODEL_ID = os.environ.get("OCR_MODEL", "lightonai/LightOnOCR-3-4B")
MAX_TOKENS = int(os.environ.get("OCR_MAX_TOKENS", "2048"))
ATTN_IMPL = os.environ.get("OCR_ATTN_IMPL", "sdpa")
# LightOnOCR-3: "" = full-page transcription; "grounding" = bounding boxes only.
PROMPT = os.environ.get("OCR_PROMPT", "")

torch = None
AutoProcessor = None
Qwen3_5ForConditionalGeneration = None
_session = None


def cuda_session():
    """Load the model once on CUDA, preloaded at app startup."""
    global _session, torch, AutoProcessor, Qwen3_5ForConditionalGeneration
    if _session is None:
        if torch is None:
            import torch as _torch
            from transformers import (
                AutoProcessor as _AutoProcessor,
                Qwen3_5ForConditionalGeneration as _Model,
            )

            torch = _torch
            AutoProcessor = _AutoProcessor
            Qwen3_5ForConditionalGeneration = _Model
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available on this host")
        model = Qwen3_5ForConditionalGeneration.from_pretrained(
            MODEL_ID,
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPL,
            low_cpu_mem_usage=True,
        )
        model = model.to("cuda").eval()
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        _session = (model, processor)
    return _session


class CudaBackend:
    def extract_page(self, image: Image.Image) -> str:
        model, processor = cuda_session()
        content = [{"type": "image", "image": image}]
        if PROMPT:
            content.append({"type": "text", "text": PROMPT})
        conversation = [{"role": "user", "content": content}]
        inputs = processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to("cuda")
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=MAX_TOKENS,
                do_sample=False,
            )
        generated = output[0, inputs["input_ids"].shape[1] :]
        return processor.decode(generated, skip_special_tokens=True).strip()
