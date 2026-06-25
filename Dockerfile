FROM python:3.11-slim

# curl per healthcheck; le altre libs sono richieste da WeasyPrint (genera-proposta-pdf)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 \
    libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

ENV GDRIVE_CREDENTIALS_FILE=/app/credentials.json
ENV GDRIVE_TOKEN_FILE=/app/token.json

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "10"]
