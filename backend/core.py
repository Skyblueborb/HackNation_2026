import logging
from errors import PdfError

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500


def render_pages(pdf: bytes) -> list:          raise NotImplementedError
def fix_rotation(pages: list) -> tuple:        raise NotImplementedError  # -> (pages, rotations)
def extract_text(pages: list) -> str:          raise NotImplementedError
def classify(text: str) -> str:                raise NotImplementedError
def extract_json(text: str, doc_type: str) -> tuple:  raise NotImplementedError  # -> (dict, unsure_fields)


def process(pdf: bytes) -> dict:
    r = {"ok": True, "step0": {}, "step1": {}, "step2": {}, "step3": {}, "step4": None, "error": None}

    def fail(exc: PdfError) -> dict:
        logger.warning(exc)
        r["ok"] = False
        r["error"] = {"atStep": exc.step, "code": exc.code, "message": exc.message, "detail": exc.detail}
        return r

    # step 0 — walidacja wejścia
    try:
        if not pdf:                        raise PdfError("EMPTY_FILE",          0, "File is empty.")
        if len(pdf) > MAX_PDF_BYTES:       raise PdfError("FILE_TOO_LARGE",      0, f"Exceeds {MAX_PDF_BYTES // 1024**2} MB.")
        if not pdf.startswith(b"%PDF"):    raise PdfError("INVALID_PDF_HEADER",  0, "Not a PDF file.")
        r["step0"]["valid"] = True
    except PdfError as e:
        return fail(e)

    # step 1 — renderowanie stron
    try:
        pages = render_pages(pdf)
        if not pages:              raise PdfError("NO_PAGES",           1, "PDF has 0 pages.")
        if len(pages) > MAX_PAGES: raise PdfError("PAGE_LIMIT_EXCEEDED",1, f"Too many pages ({len(pages)}).")
        r["step1"]["pageCount"] = len(pages)
    except PdfError as e:
        return fail(e)
    except Exception as e:
        return fail(PdfError("RENDER_FAILED", 1, str(e)))

    # step 2 — korekcja rotacji
    try:
        pages, rotations = fix_rotation(pages)
        r["step2"]["pagesRotation"] = rotations
    except PdfError as e:
        return fail(e)
    except Exception as e:
        return fail(PdfError("ROTATION_FAILED", 2, str(e)))

    # step 3 — OCR / ekstrakcja tekstu
    try:
        text = extract_text(pages)
        if not text.strip(): raise PdfError("EMPTY_TEXT", 3, "OCR produced no text.")
        r["step3"]["textLength"] = len(text)
    except PdfError as e:
        return fail(e)
    except Exception as e:
        return fail(PdfError("OCR_FAILED", 3, str(e)))

    # step 4 — klasyfikacja + ekstrakcja pól
    try:
        doc_type = classify(text)
        if doc_type == "invalid":
            r["step4"] = {"rodzaj": "invalid", "json": {}, "unsureFields": []}
            return r
        extracted, unsure = extract_json(text, doc_type)
        r["step4"] = {"rodzaj": doc_type, "json": extracted, "unsureFields": unsure}
    except PdfError as e:
        return fail(e)
    except Exception as e:
        return fail(PdfError("EXTRACT_FAILED", 4, str(e)))

    return r
