#!/usr/bin/env python3
"""
api_server.py

HTTP REST API server che espone gli script Python come endpoint REST
per N8N e altri client HTTP.

Endpoints:
    GET  /health              → health check
    POST /gdrive-to-pdf       → converti cartella Drive in PDF
    POST /auth/token          → aggiorna il token Google OAuth2 (chiamato da N8N)
"""

import json
import logging
import os
from pathlib import Path

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
    dst: str
    output: str = "merged.pdf"


class GdriveToPdfResponse(BaseModel):
    id: str
    name: str
    webViewLink: str


class GoogleTokenRequest(BaseModel):
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str
    client_secret: str
    scopes: list[str] = []
    expiry: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """Health check per Docker e N8N."""
    return {"status": "ok"}


@app.post("/gdrive-to-pdf", response_model=GdriveToPdfResponse)
async def gdrive_to_pdf(body: GdriveToPdfRequest) -> GdriveToPdfResponse:
    """
    Converte tutti i file di una cartella Google Drive in un unico PDF
    e lo carica nella cartella di destinazione.
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


@app.post("/auth/token")
async def update_token(body: GoogleTokenRequest) -> dict:
    """
    Aggiorna il token Google OAuth2 salvato in token.json.

    Chiamato da N8N dopo aver ottenuto un nuovo access_token da Google
    (POST https://oauth2.googleapis.com/token).

    N8N deve passare tutti i campi ricevuti da Google più client_id,
    client_secret e refresh_token (che N8N custodisce).
    """
    token_data = {
        "token": body.access_token,
        "refresh_token": body.refresh_token,
        "token_uri": body.token_uri,
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "scopes": body.scopes,
        "expiry": body.expiry,
    }
    try:
        Path(TOKEN_FILE).write_text(json.dumps(token_data, indent=2))
        logging.info("token.json aggiornato da N8N")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
