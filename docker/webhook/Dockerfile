FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Il container gira come root (uid 0) ma il repo bind-montato in /repo è di ubuntu
# (uid 1000): senza questo, git rifiuta con "dubious ownership" e il deploy fallisce.
# In /etc/gitconfig (system) → persiste a ogni ricreazione del container.
RUN git config --system --add safe.directory '*'

RUN pip install --no-cache-dir fastapi uvicorn

WORKDIR /app
COPY server.py .

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
