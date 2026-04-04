# claude_py_experimental_repo

Script Python invocabili da **N8N** (HTTP POST) e **Claude Code** (MCP).

---

## Architettura

```
VPS
└── /opt/docker/                    ← cartella dove hai già il tuo stack
    ├── docker-compose.yml          ← il TUO file, aggiungi i due servizi
    ├── .env
    └── python-utils/               ← repo clonato qui come sottocartella
        ├── scripts/
        ├── mcp_server.py
        ├── api_server.py
        └── Dockerfile
```

I container python-utils e claude-code vengono aggiunti al tuo stack esistente.
Condividono la stessa rete Docker di n8n e si vedono per nome.

---

## Installazione

### 1. Vai nella cartella dove hai già il tuo docker-compose.yml

```bash
ssh user@ip-vps
cd /opt/docker          # ← adatta al tuo percorso reale
```

### 2. Clona il repo come sottocartella

```bash
git clone <repo-url> python-utils
```

### 3. Copia le credenziali Google dentro la sottocartella

```bash
# Dal tuo PC (non dal VPS)
scp credentials.json token.json user@ip-vps:/opt/docker/python-utils/
```

> Se non hai ancora `token.json` vedi la sezione "Token Google OAuth2" in fondo.

### 4. Aggiungi i due servizi al tuo docker-compose.yml esistente

Apri `/opt/docker/docker-compose.yml` e aggiungi dentro `services:`:

```yaml
  python-utils:
    build: ./python-utils
    container_name: python-utils
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./python-utils/credentials.json:/app/credentials.json:ro
      - ./python-utils/token.json:/app/token.json
    environment:
      GDRIVE_CREDENTIALS_FILE: /app/credentials.json
      GDRIVE_TOKEN_FILE: /app/token.json
    networks:
      - <nome-rete-esistente>      # stesso nome della rete di n8n

  claude-code:
    build: ./python-utils/docker/claude-code
    container_name: claude-code
    restart: unless-stopped
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./python-utils:/workspace
      - claude-config:/root/.claude
      - ./python-utils/docker/claude-code/.mcp.json.example:/root/.claude/mcp.json:ro
    networks:
      - <nome-rete-esistente>
    depends_on:
      - python-utils
    stdin_open: true
    tty: true
```

Aggiungi `claude-config` nella sezione `volumes:` del tuo compose:

```yaml
volumes:
  claude-config:
```

Aggiungi `ANTHROPIC_API_KEY` nel tuo `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 5. Avvia i nuovi container

```bash
docker compose up -d --build python-utils claude-code
```

### 6. Verifica

```bash
docker compose ps
curl http://localhost:8000/health    # → {"status":"ok"}
```

---

## Aggiornare il codice

```bash
cd /opt/docker/python-utils
git pull
cd ..
docker compose up -d --build python-utils
```

---

## Usare Claude Code

```bash
docker exec -it claude-code claude
```

I tool MCP sono già configurati e pronti.

---

## API HTTP per N8N

### `POST /gdrive-to-pdf`

Nel nodo **HTTP Request** di N8N:

```
Method:  POST
URL:     http://python-utils:8000/gdrive-to-pdf
Body:
{
  "src":    "https://drive.google.com/drive/folders/SOURCE_ID",
  "dst":    "https://drive.google.com/drive/folders/DEST_ID",
  "output": "report.pdf"
}
```

Risposta:
```json
{
  "id": "1xYz...",
  "name": "report.pdf",
  "webViewLink": "https://drive.google.com/file/d/1xYz.../view"
}
```

Swagger UI: `http://ip-vps:8000/docs`

---

## Tool MCP per Claude Code

### `gdrive_folder_to_pdf`

| Parametro | Obbligatorio | Default | Descrizione |
|---|---|---|---|
| `src` | si | — | URL cartella Drive sorgente |
| `dst` | si | — | URL cartella Drive destinazione |
| `output` | no | `merged.pdf` | Nome del PDF di output |

---

## Token Google OAuth2 (solo prima volta)

Il token richiede un browser. Farlo dal tuo PC:

```bash
# Sul tuo PC
pip install google-auth-oauthlib google-api-python-client pypdf
python python-utils/scripts/gdrive_folder_to_pdf.py \
  --src "URL_SORGENTE" --dst "URL_DESTINAZIONE"
# Si apre il browser → autorizza → viene creato token.json

# Copia sul VPS
scp credentials.json token.json user@ip-vps:/opt/docker/python-utils/
```

Da quel momento il token si rinnova automaticamente.

---

## Scripts disponibili

| Script | Endpoint | Tool MCP | Descrizione |
|---|---|---|---|
| `scripts/gdrive_folder_to_pdf.py` | `POST /gdrive-to-pdf` | `gdrive_folder_to_pdf` | Cartella Drive → PDF unico |

---

## Aggiungere nuovi script

1. Crea `scripts/nuovo_script.py` con funzione `run(...)`
2. Registra il tool in `mcp_server.py`
3. Aggiungi l'endpoint in `api_server.py`
4. Aggiorna la tabella qui sopra
5. `git push` → sul VPS `git pull && docker compose up -d --build python-utils`
