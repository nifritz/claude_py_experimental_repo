# Dockerfile
# Immagine unica che espone:
#   - API HTTP (porta 8000) per N8N  →  CMD di default
#   - MCP server via stdio per Claude Code  →  docker exec -i <container> python mcp_server.py

FROM python:3.11-slim

WORKDIR /app

# Dipendenze di sistema minime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installa dipendenze Python
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copia il codice
COPY . .

# Volumi attesi a runtime (credenziali Google):
#   /app/credentials.json  → OAuth2 client secret
#   /app/token.json        → token salvato (creato al primo run)

# Variabili d'ambiente di default
ENV GDRIVE_CREDENTIALS_FILE=/app/credentials.json
ENV GDRIVE_TOKEN_FILE=/app/token.json

# Healthcheck per Docker / N8N
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: avvia il server HTTP per N8N
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
