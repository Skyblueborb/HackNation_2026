def render_pages(pdf: bytes) -> list:
    """PDF -> lista obrazów stron."""
    raise NotImplementedError


def fix_rotation(pages: list) -> list:
    """Prostuje obrócone/przekrzywione strony."""
    raise NotImplementedError


def extract_text(pages: list) -> str:
    """OCR: obrazy -> tekst."""
    raise NotImplementedError


def classify(text: str) -> str:
    """Tekst -> typ dokumentu (np. 'przelew', 'pelnomocnictwo', 'odwolanie', 'invalid')."""
    raise NotImplementedError


def extract_json(text: str, doc_type: str) -> dict:
    """Tekst + typ -> JSON z polami biznesowymi."""
    raise NotImplementedError


def process(pdf: bytes) -> dict:
    pages = render_pages(pdf)
    pages = fix_rotation(pages)
    text = extract_text(pages)
    doc_type = classify(text)
    if doc_type == "invalid":
        return {"rodzaj": "invalid"}
    return {"rodzaj": doc_type, "json": extract_json(text, doc_type)}