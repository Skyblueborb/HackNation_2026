import asyncio
import io
import sys
import threading
import time
import types

from PIL import Image

from ocr_common import OCRDocument, load_llm_processor, run_analyze_async, run_ocr_async
from ocr_common import pipeline


def pdf_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PDF")
    return buf.getvalue()


async def _fake_textlayer(data, *, processor=None, filename=None):
    return {"backend": "text", "filename": filename}


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


def test_pipeline_passes_filename_to_processor():
    class Recorder:
        def process(self, document):
            return {"filename": document.filename}

    result = asyncio.run(
        run_ocr_async(
            pdf_bytes(),
            FakeExtractor(),
            backend="test",
            model="m",
            processor=Recorder(),
            filename="odwolanie.pdf",
        )
    )
    assert result["llm"] == {"filename": "odwolanie.pdf"}


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


def test_run_ocr_async_serializes_ocr_but_not_llm():
    entered = asyncio.Event()
    release = threading.Event()
    active = {"count": 0, "max": 0}

    class SlowExtractor:
        def extract_page(self, image):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            time.sleep(0.02)
            active["count"] -= 1
            return "text"

    class BlockingProcessor:
        def __init__(self, loop):
            self.loop = loop

        def process(self, document):
            self.loop.call_soon_threadsafe(entered.set)
            release.wait(timeout=2)
            return {"ok": True}

    async def scenario():
        loop = asyncio.get_running_loop()
        first = asyncio.create_task(
            run_ocr_async(
                pdf_bytes(),
                SlowExtractor(),
                backend="test",
                model="m",
                processor=BlockingProcessor(loop),
                filename="a.pdf",
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        second = asyncio.create_task(
            run_ocr_async(
                pdf_bytes(), SlowExtractor(), backend="test", model="m", filename="b.pdf"
            )
        )
        # Second request finishes OCR while first still waits on the LLM.
        await asyncio.wait_for(second, timeout=2)
        assert not first.done()
        release.set()
        await asyncio.wait_for(first, timeout=2)
        assert first.result()["llm"] == {"ok": True}

    asyncio.run(scenario())
    assert active["max"] == 1


def test_analyze_routes_image_pdf_to_ocr():
    """A PDF with no text layer still goes through the OCR extractor."""
    result = asyncio.run(
        run_analyze_async(
            pdf_bytes(),
            FakeExtractor(),
            backend="test",
            model="m",
        )
    )
    assert result["backend"] == "test"
    assert result["pages"] == [{"page": 1, "text": "text"}]


def test_analyze_prefers_text_layer_and_skips_ocr(monkeypatch):
    class Exploding:
        def extract_page(self, image):
            raise AssertionError("OCR must not run when a text layer exists")

    monkeypatch.setattr(pipeline, "_has_text_layer", lambda data: True)
    monkeypatch.setattr(
        pipeline,
        "run_textlayer_async",
        _fake_textlayer,
    )
    result = asyncio.run(
        run_analyze_async(
            pdf_bytes(),
            Exploding(),
            backend="test",
            model="m",
            filename="x.pdf",
        )
    )
    assert result == {"backend": "text", "filename": "x.pdf"}


def test_analyze_falls_back_to_ocr_when_gate_raises(monkeypatch):
    def boom(data):
        raise ValueError("not a pdf")

    monkeypatch.setattr(pipeline, "_has_text_layer", boom)
    result = asyncio.run(
        run_analyze_async(
            pdf_bytes(),
            FakeExtractor(),
            backend="test",
            model="m",
        )
    )
    assert result["pages"] == [{"page": 1, "text": "text"}]
