"""CUDA backend for LightOnOCR-3 in full BF16 (0.8B default)."""

from __future__ import annotations

import os
import time

from PIL import Image

from ocr_common.common import logger

MODEL_ID = os.environ.get("OCR_MODEL", "lightonai/LightOnOCR-3-0.8B")
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
        logger.info(
            "cuda_session ready: model=%s attn=%s torch=%s cuda=%s",
            MODEL_ID,
            ATTN_IMPL,
            torch.__version__,
            torch.version.cuda,
        )
        _session = (model, processor)
    return _session


def warmup() -> None:
    """Trigger CUDA/Triton kernel compilation before the first real request."""
    model, processor = cuda_session()
    image = Image.new("RGB", (64, 64), "white")
    conversation = [
        {
            "role": "user",
            "content": [{"type": "image", "image": image}],
        }
    ]
    started = time.perf_counter()
    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        enable_thinking=False,
    ).to("cuda")
    with torch.inference_mode():
        model.generate(**inputs, max_new_tokens=1, do_sample=False)
    logger.info("cuda warmup done in %.2fs", time.perf_counter() - started)


class CudaBackend:
    def extract_page(self, image: Image.Image) -> str:
        model, processor = cuda_session()
        content = [{"type": "image", "image": image}]
        if PROMPT:
            content.append({"type": "text", "text": PROMPT})
        conversation = [{"role": "user", "content": content}]
        started = time.perf_counter()
        inputs = processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to("cuda")
        prepared = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=MAX_TOKENS,
                do_sample=False,
            )
        generated_at = time.perf_counter()
        generated = output[0, inputs["input_ids"].shape[1] :]
        text = processor.decode(generated, skip_special_tokens=True).strip()
        logger.info(
            "ocr generate: prep=%.2fs generate=%.2fs tokens=%d chars=%d",
            prepared - started,
            generated_at - prepared,
            generated.shape[-1],
            len(text),
        )
        return text
