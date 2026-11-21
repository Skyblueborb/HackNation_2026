# Architecture description

## Overview

The system changes a PDF file into a JSON file. It does not save the PDF on disk. It keeps all data in memory. Data is lost when the process ends.

## Core

The core has one function: `process`. The function receives the PDF as bytes. It returns a JSON object. It does these steps in order:

1. **Render.** The function changes each PDF page into an image.
2. **Fix rotation.** The function turns and straightens the page images.
3. **Extract text.** The function uses OCR to read the text from the images.
4. **Classify.** The function finds the document type. The type is one of three types, or "invalid".
5. **Extract JSON.** The function uses an LLM to change the text into JSON. The JSON fields depend on the document type.

If the type is "invalid", the function stops. It returns `{"rodzaj": "invalid"}`.

## Interfaces

The core does not know where the PDF comes from. It does not know where the result goes. Two thin adapters call the core.

- **CLI.** The user gives a folder. The CLI finds each PDF in the folder and in its sub-folders. It calls `process` for each file. It prints one JSON line for each file.
- **API.** The frontend sends a PDF with a POST request. The API calls `process`. The API sends the JSON back in the response.

## Rules

- The system does not save PDF files, images, or text on disk.
- The system uses only open source components.
- The system runs on a local computer. It does not need a GPU. The LLM is used through an API.
- A new step or a new document type changes only the core. The CLI and the API do not change.

## Output

The output is a JSON object with these fields:

- `rodzaj`: the document type.
- `json`: the data from the document. This field is not in the output for an invalid document.