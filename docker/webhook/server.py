"""
Webhook server per deploy automatico.

Ascolta POST /deploy da Gitea/GitHub.
Verifica la firma HMAC, poi esegue:
  git pull  →  docker compose up -d --build python-utils

Variabili d'ambiente richieste:
  DEPLOY_SECRET      → segreto condiviso con Gitea/GitHub
  REPO_PATH          → path del repo clonato sull'host (montato nel container)
  COMPOSE_PATH       → path della cartella con docker-compose.yml (montato)
  COMPOSE_SERVICES   → servizi da rebuil dare, separati da spazio (default: python-utils)
"""

import hashlib
import hmac
import logging
import os
import subprocess

from fastapi import FastAPI, Header, HTTPException, Request

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

DEPLOY_SECRET = os.environ["DEPLOY_SECRET"].encode()
REPO_PATH = os.environ.get("REPO_PATH", "/repo")
COMPOSE_PATH = os.environ.get("COMPOSE_PATH", "/compose")
COMPOSE_SERVICES = os.environ.get("COMPOSE_SERVICES", "python-utils").split()

app = FastAPI(title="Deploy Webhook")


def _verify_signature(body: bytes, signature: str | None) -> None:
    """Verifica firma HMAC-SHA256 (formato Gitea/GitHub: sha256=<hex>)."""
    if not signature:
        raise HTTPException(status_code=401, detail="Firma mancante")
    expected = "sha256=" + hmac.new(DEPLOY_SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Firma non valida")


def _run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"Comando fallito ({' '.join(cmd)}): {output}")
    return output


@app.post("/deploy")
async def deploy(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_gitea_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    signature = x_hub_signature_256 or ("sha256=" + x_gitea_signature if x_gitea_signature else None)
    _verify_signature(body, signature)

    log.info("Deploy avviato...")
    try:
        out_pull = _run(["git", "pull"], cwd=REPO_PATH)
        log.info("git pull: %s", out_pull)

        out_compose = _run(
            ["docker", "compose", "up", "-d", "--build", *COMPOSE_SERVICES],
            cwd=COMPOSE_PATH,
        )
        log.info("docker compose: %s", out_compose)
    except RuntimeError as e:
        log.error("%s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "git": out_pull, "compose": out_compose}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
