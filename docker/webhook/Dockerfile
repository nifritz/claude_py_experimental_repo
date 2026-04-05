FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn

WORKDIR /app
COPY server.py .

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
