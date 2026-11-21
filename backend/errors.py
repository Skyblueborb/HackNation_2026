class PdfError(Exception):
    def __init__(self, code: str, step: int, message: str, **detail):
        self.code, self.step, self.message, self.detail = code, step, message, detail
        super().__init__(message)
