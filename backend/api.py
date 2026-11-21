from fastapi import FastAPI, UploadFile
from core import process

app = FastAPI()


@app.post("/process")
async def process_pdf(file: UploadFile):
    return process(await file.read())
