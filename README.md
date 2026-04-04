# claude_py_experimental_repo

Esperimenti con Claude Code in Python.

> Questo repository contiene script Python eseguibili all'interno di un container Docker,
> invocabili da **N8N** (via HTTP POST) e da **Claude Code** (via MCP).

---

## Architettura completa

```
VPS
│
└── docker-compose.yml  (rete interna: vps-net)
    │
    ├── mariadb          ← database per N8N
    │     └── porta 3306 (interna)
    │
    ├── n8n              ← orchestratore workflow
    │     ├── porta 5678 (esposta)
    │     └── HTTP POST ──────────────────────────────────┐
    │                                                     │
    ├── claude-code       ← Claude Code CLI               │
    │     ├── ANTHROPIC_API_KEY                           │
    │     ├── /var/run/docker.sock (montato)              │
    │     └── docker exec -i python-utils ──────────┐    │
    │          (trasporto MCP stdio)                 │    │
    │                                                ▼    ▼
    └── python-utils      ← questo repository
          ├── porta 8000 (interna + opzionale esposta)
          ├── mcp_server.py   ← risponde a Claude via stdin/stdout
          ├── api_server.py   ← risponde a N8N via HTTP REST
          └── scripts/        ← logica condivisa
```

**Punto chiave:** `mcp_server.py` e `api_server.py` condividono gli stessi script
sotto `scripts/` — un solo codebase, due canali di accesso.

---

## Scripts disponibili

| Script | Descrizione | Endpoint HTTP | Tool MCP |
|---|---|---|---|
| `scripts/gdrive_folder_to_pdf.py` | Converte cartella Drive → PDF unificato | `POST /gdrive-to-pdf` | `gdrive_folder_to_pdf` |

---

## Setup completo da zero

### 1. Prerequisiti sul VPS

```bash
# Docker + Docker Compose
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin

# Clona il repo
git clone <repo-url> /opt/python-utils
cd /opt/python-utils
```

### 2. Variabili d'ambiente

```bash
cp .env.example .env
nano .env   # compila tutti i valori
```

Valori obbligatori:

| Variabile | Descrizione |
|---|---|
| `ANTHROPIC_API_KEY` | API key Anthropic per Claude Code |
| `MYSQL_ROOT_PASSWORD` | Password root MariaDB |
| `MYSQL_PASSWORD` | Password utente N8N su MariaDB |
| `N8N_ENCRYPTION_KEY` | Stringa random ≥32 caratteri per N8N |
| `N8N_WEBHOOK_URL` | URL pubblico di N8N (es. `https://n8n.tuodominio.com`) |

### 3. Credenziali Google OAuth2

1. [Google Cloud Console](https://console.cloud.google.com/) → abilita **Google Drive API**
2. Crea credenziali OAuth 2.0 → tipo *Desktop app* (più semplice per token offline)
3. Scarica il JSON → salvalo come `credentials.json` nella root del progetto
4. Genera `token.json` **una volta** in locale (richiede browser):

```bash
# In locale (non sul VPS) — serve il browser per il consenso OAuth
pip install google-auth-oauthlib google-api-python-client pypdf
python scripts/gdrive_folder_to_pdf.py \
  --src "https://drive.google.com/drive/folders/SOURCE_ID" \
  --dst "https://drive.google.com/drive/folders/DEST_ID"

# Copia i file sul VPS
scp credentials.json token.json user@vps:/opt/python-utils/
```

> Da quel momento il token si rinnova automaticamente senza browser.

### 4. Configura MCP per Claude Code

```bash
# Copia il template MCP nel volume di Claude Code
# (da fare dopo il primo avvio del container)
cp docker/claude-code/.mcp.json.example /tmp/.mcp.json

# Oppure monta il file direttamente — vedi sezione "Integrazione MCP"
```

### 5. Avvia lo stack

```bash
docker compose up -d

# Verifica che tutto sia su
docker compose ps
docker compose logs -f python-utils
```

### 6. Verifica

```bash
# Health check python-utils (dall'host)
curl http://localhost:8000/health
# → {"status": "ok"}

# Health check dall'interno della rete (es. da N8N)
docker exec n8n wget -qO- http://python-utils:8000/health
```

---

## Integrazione N8N

### Connessione a python-utils

N8N e python-utils sono sulla stessa rete `vps-net` → comunicano per nome container.

### Endpoint disponibili

#### `GET /health`

```
GET http://python-utils:8000/health
```

```json
{ "status": "ok" }
```

#### `POST /gdrive-to-pdf`

**Request:**
```json
{
  "src": "https://drive.google.com/drive/folders/SOURCE_FOLDER_ID",
  "dst": "https://drive.google.com/drive/folders/DEST_FOLDER_ID",
  "output": "report_aprile_2026.pdf"
}
```

| Campo | Tipo | Obbligatorio | Default |
|---|---|---|---|
| `src` | string | si | — |
| `dst` | string | si | — |
| `output` | string | no | `merged.pdf` |

**Response:**
```json
{
  "id": "1xYz_AbCdEfGhIjKlMnOpQr",
  "name": "report_aprile_2026.pdf",
  "webViewLink": "https://drive.google.com/file/d/1xYz.../view"
}
```

### Nodo N8N — HTTP Request

```
Method:       POST
URL:          http://python-utils:8000/gdrive-to-pdf
Content-Type: application/json
Body (JSON):
{
  "src":    "{{ $json.src_folder_url }}",
  "dst":    "{{ $json.dst_folder_url }}",
  "output": "{{ $json.output_name }}"
}
```

Documentazione API interattiva (Swagger): `http://localhost:8000/docs`

---

## Integrazione MCP (Claude Code)

### Come funziona

Claude Code usa il trasporto **stdio**: per ogni sessione avvia un processo MCP
e comunica via stdin/stdout. Essendo Claude Code in un container Docker, il comando
è un `docker exec -i` verso il container `python-utils`.

**Prerequisito:** il container `claude-code` ha il Docker socket montato
(`/var/run/docker.sock`) — già configurato nel `docker-compose.yml`.

### Configurazione `.mcp.json`

Il file `.mcp.json` deve trovarsi nel workspace di lavoro di Claude Code
(la cartella da cui si avvia) **oppure** in `~/.claude/` dentro il container.

**Opzione A — per progetto** (`.mcp.json` nella root del repo che si sta usando):

```json
{
  "mcpServers": {
    "python-utils": {
      "command": "docker",
      "args": [
        "exec", "-i", "python-utils",
        "python", "/app/mcp_server.py"
      ]
    }
  }
}
```

**Opzione B — globale** (dentro il container claude-code, in `/root/.claude/mcp.json`):

```bash
docker exec -it claude-code bash -c \
  'mkdir -p ~/.claude && cp /workspace/.mcp.json ~/.claude/mcp.json'
```

Il template è disponibile in `docker/claude-code/.mcp.json.example`.

### Avviare una sessione Claude Code

```bash
docker exec -it claude-code claude
```

Claude Code si avvia nel container, carica il server MCP `python-utils`
e i tool sono immediatamente disponibili.

### Tool MCP disponibili

#### `gdrive_folder_to_pdf`

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `src` | string | si | URL o ID cartella Drive sorgente |
| `dst` | string | si | URL o ID cartella Drive destinazione |
| `output` | string | no | Nome del PDF (default: `merged.pdf`) |

**Esempio in sessione Claude Code:**

```
Usa il tool gdrive_folder_to_pdf con:
  src = "https://drive.google.com/drive/folders/SOURCE_ID"
  dst = "https://drive.google.com/drive/folders/DEST_ID"
  output = "report.pdf"
```

**Output:**
```
PDF caricato con successo.
Link: https://drive.google.com/file/d/1xYz.../view
File ID: 1xYz_AbCdEfGhIjKlMnOpQr
Nome: report.pdf
```

---

## Sviluppo locale (senza Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# API server (N8N)
uvicorn api_server:app --reload --port 8000

# MCP server (test manuale)
python mcp_server.py

# Test
pytest
```

---

## Struttura del progetto

```
claude_py_experimental_repo/
├── scripts/
│   ├── __init__.py
│   └── gdrive_folder_to_pdf.py        # Conversione cartella Drive → PDF
├── tests/
│   └── test_gdrive_folder_to_pdf.py
├── docker/
│   └── claude-code/
│       ├── Dockerfile                 # Immagine Claude Code CLI
│       └── .mcp.json.example          # Template config MCP
├── mcp_server.py                      # MCP server (stdio) per Claude Code
├── api_server.py                      # HTTP server (FastAPI) per N8N
├── Dockerfile                         # Immagine python-utils
├── docker-compose.yml                 # Stack completo (tutti i servizi)
├── pyproject.toml                     # Dipendenze Python
├── .env.example                       # Template variabili d'ambiente
├── CLAUDE.md                          # Istruzioni per AI assistants
└── README.md                          # Questo file
```

---

## Aggiungere nuovi script

1. Crea `scripts/nome_script.py` con una funzione `run(...)` pubblica
2. Registra il tool in `mcp_server.py` → `list_tools()` e `call_tool()`
3. Aggiungi l'endpoint in `api_server.py`
4. Aggiungi i test in `tests/`
5. Aggiorna la tabella "Scripts disponibili" in questo README
