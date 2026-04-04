#!/usr/bin/env python3
"""
api_server.py

HTTP REST API server that exposes Python utility scripts as endpoints
callable by N8N or any HTTP client.

Usage:
    uvicorn api_server:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health              → health check
    POST /gdrive-to-pdf       → converti cartella Drive in PDF
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from scripts.gdrive_folder_to_pdf import run as gdrive_to_pdf_run

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

CREDENTIALS_FILE = os.environ.get("GDRIVE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.environ.get("GDRIVE_TOKEN_FILE", "token.json")

app = FastAPI(
    title="Python Utils API",
    description="Utility API per N8N — espone script Python come endpoint REST.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GdriveToPdfRequest(BaseModel):
    src: str
    """URL o ID della cartella Google Drive sorgente."""
    dst: str
    """URL o ID della cartella Google Drive di destinazione."""
    output: str = "merged.pdf"
    """Nome del file PDF di output."""


class GdriveToPdfResponse(BaseModel):
    id: str
    name: str
    webViewLink: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """Health check — usato da Docker e N8N per verificare che il server sia attivo."""
    return {"status": "ok"}


@app.post("/gdrive-to-pdf", response_model=GdriveToPdfResponse)
async def gdrive_to_pdf(body: GdriveToPdfRequest) -> GdriveToPdfResponse:
    """
    Converte tutti i file in una cartella Google Drive in un unico PDF
    e lo carica nella cartella di destinazione.

    Restituisce id, nome e link del file PDF caricato.
    """
    try:
        result = gdrive_to_pdf_run(
            src_url=body.src,
            dst_url=body.dst,
            output_name=body.output,
            credentials_file=CREDENTIALS_FILE,
            token_file=TOKEN_FILE,
        )
        return GdriveToPdfResponse(
            id=result["id"],
            name=result["name"],
            webViewLink=result["webViewLink"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
