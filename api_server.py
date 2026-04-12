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
    POST /split-grid-count    → same, but finds n largest connected components (robust to irregular grids)
    POST /approssima-colori   → riduce i colori di un'immagine alla palette hardcodata
"""

import io
import logging

import requests as http_requests
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import Response
from PIL import Image

from scripts.approssima_colori import approssima
from scripts.approssima_colori import to_base64_png as approssima_to_base64
from scripts.merge_pdfs import merge
from scripts.split_grid import split, split_by_count
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


class SplitGridByCountRequest(BaseModel):
    image_url: str
    n: int


class ApprossimaColoriRequest(BaseModel):
    image_url: str
    n_colori: int = 4


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


@app.post("/split-grid-count")
def split_grid_count(req: SplitGridByCountRequest) -> dict:
    """
    Divide una sprite sheet nei n soggetti principali trovati per componenti connessi.

    Alternativa a /split-grid: non assume celle di dimensione uniforme, quindi è
    robusto a griglie irregolari generate da AI.

    Body JSON: {"image_url": "https://...", "n": 10}
    Response : {"images": [{"base64": "...", "index": 0}, ...]}
    """
    if req.n <= 0:
        raise HTTPException(status_code=400, detail="n deve essere > 0")
    if req.n > 50:
        raise HTTPException(status_code=400, detail="n deve essere <= 50")

    try:
        resp = http_requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except http_requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Errore download immagine: {e}") from e

    try:
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Immagine non valida: {e}") from e

    images = split_by_count(img, req.n)
    logging.info("split-grid-count: n=%d → %d soggetti trovati", req.n, len(images))
    return {"images": images}


@app.post("/approssima-colori")
def approssima_colori(req: ApprossimaColoriRequest) -> dict:
    """
    Riduce i colori di un'immagine ai N più vicini dalla palette hardcodata.

    Body JSON: {"image_url": "https://...", "n_colori": 4}
    Response : {"base64": "<png base64>"}
    """
    if req.n_colori <= 0:
        raise HTTPException(status_code=400, detail="n_colori deve essere > 0")

    try:
        resp = http_requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except http_requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Errore download immagine: {e}") from e

    try:
        img = Image.open(io.BytesIO(resp.content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Immagine non valida: {e}") from e

    result = approssima(img, req.n_colori)
    logging.info("approssima-colori: %d colori richiesti", req.n_colori)
    return {"base64": approssima_to_base64(result)}


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
