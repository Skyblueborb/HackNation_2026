import asyncio
import io
import sys
import types

from PIL import Image

from ocr_common import OCRDocument, load_llm_processor, run_ocr_async


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


class FakeExtractor:
    def extract_page(self, image):
        return "  text  "


class FakeProcessor:
    def __init__(self):
        self.seen = None

    def process(self, document):
        self.seen = document
        return {"ok": True}


def test_pipeline_calls_processor_with_ocr_document():
    processor = FakeProcessor()
    result = asyncio.run(
        run_ocr_async(
            pdf_bytes(),
            FakeExtractor(),
            backend="test",
            model="m",
            processor=processor,
        )
    )
    assert result["pages"] == [{"page": 1, "text": "text"}]
    assert result["llm"] == {"ok": True}
    assert isinstance(processor.seen, OCRDocument)
    assert processor.seen.pages[0].text == "text"


def test_pipeline_without_processor_has_no_llm_field():
    result = asyncio.run(
        run_ocr_async(pdf_bytes(), FakeExtractor(), backend="test", model="m")
    )
    assert "llm" not in result


def test_registry_loads_processor_object():
    module = types.ModuleType("fake_llm_module")
    module.processor = FakeProcessor()
    sys.modules["fake_llm_module"] = module
    loaded = load_llm_processor("fake_llm_module:processor")
    assert loaded is module.processor


def test_registry_wraps_callable():
    module = types.ModuleType("fake_llm_callable")
    module.factory = lambda document: {"pages": len(document.pages)}
    sys.modules["fake_llm_callable"] = module
    loaded = load_llm_processor("fake_llm_callable:factory")
    assert loaded.process(OCRDocument("b", "m", ())) == {"pages": 0}
