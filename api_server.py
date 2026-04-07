#!/usr/bin/env python3
"""
api_server.py

HTTP REST API server that exposes Python utility scripts as endpoints
callable by N8N or any HTTP client.

N8N handles Google Drive auth. It downloads files, sends them here as
multipart/form-data, and uploads the result back to Drive.

Endpoints:
    GET  /health              → health check
    POST /merge-pdfs          → merge uploaded PDFs into one
    POST /split-grid          → split a sprite sheet into individual cells (base64 PNG)
"""

import io
import logging

import requests as http_requests
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import Response
from PIL import Image

from scripts.merge_pdfs import merge
from scripts.split_grid import split
from scripts.test_hello import hello

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

app = FastAPI(
    title="Python Utils API",
    description="Utility API per N8N — espone script Python come endpoint REST.",
    version="0.2.0",
)


class HelloRequest(BaseModel):
    name: str


class SplitGridRequest(BaseModel):
    image_url: str
    rows: int
    cols: int


@app.post("/test-hello")
async def test_hello(body: HelloRequest) -> dict:
    return {"message": hello(body.name)}


@app.post("/split-grid")
def split_grid(req: SplitGridRequest) -> dict:
    """
    Divide una sprite sheet in celle singole con autocrop e padding.

    Body JSON: {"image_url": "https://...", "rows": 2, "cols": 5}
    Response : {"images": [{"base64": "...", "index": 0}, ...]}

    Usato dall'workflow n8n "Genera Prodotto Shopify Bimbi Unici".
    """
    if req.rows <= 0 or req.cols <= 0:
        raise HTTPException(status_code=400, detail="rows e cols devono essere > 0")
    if req.rows > 10 or req.cols > 10:
        raise HTTPException(status_code=400, detail="rows e cols devono essere <= 10")

    try:
        resp = http_requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except http_requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Errore download immagine: {e}") from e

    try:
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Immagine non valida: {e}") from e

    images = split(img, req.rows, req.cols)
    logging.info("split-grid: %dx%d → %d celle", req.rows, req.cols, len(images))
    return {"images": images}


@app.get("/health")
async def health() -> dict:
    """Health check per Docker e N8N."""
    return {"status": "ok"}


@app.post("/merge-pdfs")
async def merge_pdfs(
    files: list[UploadFile],
    output: str = "merged.pdf",
) -> Response:
    """
    Unisce più file PDF in un unico PDF.

    N8N invia i file come multipart/form-data (campo: files).
    Risponde con il PDF binario (application/pdf).

    Flusso N8N tipico:
      1. Google Drive → scarica ogni file come PDF (export)
      2. HTTP Request POST /merge-pdfs  ← questo endpoint
      3. Google Drive → carica il PDF ricevuto nella cartella destinazione
    """
    if not files:
        raise HTTPException(status_code=422, detail="Nessun file fornito")

    pdf_bytes_list: list[bytes] = []
    for f in files:
        content = await f.read()
        if not content:
            raise HTTPException(status_code=422, detail=f"File vuoto: {f.filename!r}")
        pdf_bytes_list.append(content)
        logging.info("Ricevuto: %s (%d bytes)", f.filename, len(content))

    try:
        merged = merge(pdf_bytes_list)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logging.info("Merged %d file(s) → %d bytes", len(pdf_bytes_list), len(merged))
    return Response(
        content=merged,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{output}"'},
    )
