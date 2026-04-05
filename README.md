# python-utils

Script Python invocabili da **N8N** (HTTP POST) e **Claude Code** (MCP).
Vive come sottocartella del tuo stack Docker esistente.

**Principio:** Python non sa nulla di Google Drive o altri servizi esterni.
N8N scarica i file, li manda qui come binari, riceve il risultato e li ricarica.

---

## Architettura

```
dockercomposepath/
├── docker-compose.yml   ← il TUO compose (n8n, mariadb + i 3 servizi sotto)
├── .env                 ← il TUO .env (aggiungi 2 variabili)
└── python-utils/        ← questo repo
```

I 3 nuovi servizi (`python-utils`, `claude-code`, `webhook`) vanno aggiunti
al tuo `docker-compose.yml` esistente — un solo file, una sola rete.

---

## Installazione

### 1 — Clona il repo

```bash
cd dockercomposepath/
git clone <repo-url> python-utils
```

### 2 — Aggiungi i servizi al tuo docker-compose.yml

Copia questi 3 blocchi nel tuo `docker-compose.yml` esistente, nella sezione `services:`:

```yaml
  python-utils:
    build:
      context: ./python-utils
      dockerfile: Dockerfile
    container_name: python-utils
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  claude-code:
    build:
      context: ./python-utils/docker/claude-code
      dockerfile: Dockerfile
    container_name: claude-code
    restart: unless-stopped
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./python-utils:/workspace
      - claude-config:/root/.claude
      - ./python-utils/docker/claude-code/.mcp.json.example:/root/.claude/mcp.json:ro
    depends_on:
      python-utils:
        condition: service_healthy
    stdin_open: true
    tty: true

  webhook:
    build:
      context: ./python-utils/docker/webhook
      dockerfile: Dockerfile
    container_name: webhook
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./python-utils:/repo
      - ./:/compose
    environment:
      DEPLOY_SECRET: ${DEPLOY_SECRET}
      COMPOSE_SERVICES: python-utils
```

Aggiungi anche il volume nella sezione `volumes:`:

```yaml
volumes:
  claude-config:
```

### 3 — Aggiungi le variabili al tuo .env

```env
ANTHROPIC_API_KEY=sk-ant-...
DEPLOY_SECRET=stringa_casuale_lunga_almeno_32_caratteri
```

### 4 — Avvia

```bash
docker compose up -d --build python-utils claude-code webhook
```

### 5 — Verifica

```bash
docker compose ps
docker exec n8n wget -qO- http://python-utils:8000/health
# → {"status":"ok"}
```

---

## Aggiornare il codice

### Automatico (push → deploy)

Configura il webhook GitHub:
- Payload URL: `http://ip-vps:9000/deploy`
- Content type: `application/json`
- Secret: valore di `DEPLOY_SECRET`
- Events: solo **Push**

### Manuale

```bash
cd dockercomposepath/python-utils && git pull && cd ..
docker compose up -d --build python-utils
```

---

## API HTTP (per N8N)

Swagger: `ssh -L 8000:localhost:8000 user@ip-vps` → `http://localhost:8000/docs`

### `GET /health`
```
→ {"status": "ok"}
```

### `POST /merge-pdfs`

Unisce più file PDF in un unico PDF.

- **Request:** `multipart/form-data`, campo `files`
- **Response:** `application/pdf` binario
- **Query param:** `?output=nome.pdf`

**Flusso N8N — Google Drive → PDF unito → Google Drive:**

```
[Trigger]
    ▼
[Google Drive] List Files in source folder
    ▼
[Loop] per ogni file:
    └─► [Google Drive] Export as PDF
    ▼
[HTTP Request] POST http://python-utils:8000/merge-pdfs?output=report.pdf
               Body: Form-Data → files: tutti i PDF
    ▼
[Google Drive] Upload risultato in destination folder
```

---

## Claude Code (MCP)

```bash
docker exec -it claude-code claude
```

### Un server MCP per dominio

Non un unico server con tutto dentro — un server per ogni dominio coerente,
ognuno un processo stdio separato registrato in `.mcp.json`.

```
mcp_servers/
├── pdf.py      ← merge_pdfs (funzionante)
├── images.py   ← scheletro
└── data.py     ← scheletro
```

Quando aggiungi uno script, scegli il server giusto per dominio.
Se nessuno è adatto, crei `mcp_servers/nuovo.py` e aggiungi l'entry in `.mcp.json`.

### Tool disponibili

| Server | Tool | Descrizione |
|---|---|---|
| `pdf` | `merge_pdfs` | Unisce file PDF locali |
| `images` | *(scheletro)* | — |
| `data` | *(scheletro)* | — |

---

## Aggiungere nuovi script

1. Crea `scripts/nome.py` — logica pura, nessun auth
2. Scegli il server MCP giusto in `mcp_servers/` e aggiungi il tool
3. Aggiungi l'endpoint in `api_server.py` se serve a N8N
4. `git push` → deploy automatico

---

## Struttura

```
python-utils/
├── scripts/
│   ├── __init__.py
│   └── merge_pdfs.py
├── mcp_servers/
│   ├── pdf.py
│   ├── images.py
│   └── data.py
├── docker/
│   ├── claude-code/Dockerfile
│   ├── claude-code/.mcp.json.example
│   └── webhook/
│       ├── Dockerfile
│       └── server.py
├── api_server.py
├── Dockerfile
├── pyproject.toml
└── .env.example
```
