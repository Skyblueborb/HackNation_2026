from fastapi import FastAPI, Response, UploadFile
from core import process

app = FastAPI()


@app.post("/process")
async def process_pdf(file: UploadFile, response: Response):
    result = process(await file.read())
    # Gdy pipeline się nie powiódł, zwracamy 422 żeby klient mógł od razu
    # sprawdzić po statusie HTTP bez parsowania ciała.
    if not result["ok"]:
        response.status_code = 422
    return result
