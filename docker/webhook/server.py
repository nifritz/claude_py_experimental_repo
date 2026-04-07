"""
Webhook server per deploy automatico al push su GitHub.

Variabili d'ambiente:
  DEPLOY_SECRET   Segreto condiviso con GitHub (obbligatorio)
  REPO_PATH       Path del repo montato nel container (default: /repo)
  COMPOSE_PATH    Path della cartella con docker-compose.yml (default: /compose)
  COMPOSE_SERVICES  Servizi da rebuilddare, separati da spazio (default: python-utils)
"""

import hashlib
import hmac
import json
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
    if not signature:
        raise HTTPException(status_code=401, detail="Firma mancante")
    expected = "sha256=" + hmac.new(DEPLOY_SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Firma non valida")


def _run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {output}")
    return output


@app.post("/deploy")
async def deploy(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    payload = json.loads(body)
    if payload.get("ref") != "refs/heads/main":
        log.info("Push su branch non-main, ignorato.")
        return {"status": "ignored"}

    log.info("Deploy avviato...")
    try:
        _run(["git", "stash"], cwd=REPO_PATH)
        out_pull = _run(["git", "pull"], cwd=REPO_PATH)
        log.info("git pull: %s", out_pull)

        out_compose = _run(
            ["docker", "compose", "up", "-d", "--build", *COMPOSE_SERVICES],
            cwd=COMPOSE_PATH,
        )
        log.info("docker compose: %s", out_compose)

        _run(["docker", "image", "prune", "-f"], cwd=COMPOSE_PATH)
        log.info("Immagini vecchie rimosse")

    except RuntimeError as e:
        log.error("%s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "git": out_pull, "compose": out_compose}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
