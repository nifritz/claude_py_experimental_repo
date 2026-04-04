# claude_py_experimental_repo

Esperimenti con Claude Code in Python.

> Questo repository contiene script Python eseguibili all'interno di un container Docker,
> invocabili da **N8N** (via HTTP POST) e da **Claude Code** (via MCP).

---

## Architettura

```
┌─────────────────────────────────────────────┐
│              Docker Host (VPS)              │
│                                             │
│  ┌─────────────┐     HTTP POST (port 8000)  │
│  │    N8N      │ ──────────────────────────►│
│  │  container  │                            │
│  └─────────────┘     ┌────────────────────┐ │
│                      │  python-utils      │ │
│  ┌─────────────┐     │  container         │ │
│  │ Claude Code │     │                    │ │
│  │  (MCP)      │────►│  api_server.py     │ │
│  │  container  │stdio│  (FastAPI, :8000)  │ │
│  └─────────────┘     │                    │ │
│   docker exec -i     │  mcp_server.py     │ │
│                      │  (stdio)           │ │
│                      └────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## Scripts disponibili

| Script | Descrizione | Endpoint HTTP | Tool MCP |
|---|---|---|---|
| `scripts/gdrive_folder_to_pdf.py` | Converte cartella Drive → PDF unificato | `POST /gdrive-to-pdf` | `gdrive_folder_to_pdf` |

---

## Setup iniziale

### 1. Credenziali Google OAuth2

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Abilita l'API: **Google Drive API**
3. Crea credenziali **OAuth 2.0** → tipo *Web application* o *Desktop app*
4. Scarica il JSON e salvalo come `credentials.json` nella root del progetto
5. Al primo avvio lo script apre il browser per autorizzare → salva `token.json`

```bash
cp .env.example .env
# Modifica .env con i path reali se necessario
```

### 2. Build e avvio Docker

```bash
# Build dell'immagine
docker build -t python-utils .

# Avvio con docker-compose (consigliato)
docker-compose up -d

# Oppure manualmente
docker run -d \
  --name python-utils \
  -p 8000:8000 \
  -v $(pwd)/credentials.json:/app/credentials.json:ro \
  -v $(pwd)/token.json:/app/token.json \
  python-utils
```

### 3. Prima autorizzazione OAuth2

Il token deve essere generato **la prima volta** con browser aperto. Fallo fuori dal container:

```bash
# Installa dipendenze localmente (solo per il primo token)
pip install -e .

# Esegui lo script una volta per generare token.json
python scripts/gdrive_folder_to_pdf.py \
  --src "https://drive.google.com/drive/folders/SOURCE_ID" \
  --dst "https://drive.google.com/drive/folders/DEST_ID"

# token.json viene creato → montalo nel container
```

---

## Integrazione N8N

Il container espone un'API REST su `http://python-utils:8000`.

### Connessione N8N → container Python

Se N8N e il container Python sono sulla stessa rete Docker, aggiungila a `docker-compose.yml`:

```yaml
# docker-compose.yml — aggiungi la rete di N8N
networks:
  utils-net:
    external: true
    name: n8n_default   # nome della rete Docker di N8N
```

### Endpoint disponibili

#### `GET /health`
Verifica che il server sia attivo.

```
GET http://python-utils:8000/health
```

Risposta:
```json
{ "status": "ok" }
```

#### `POST /gdrive-to-pdf`
Converte tutti i file di una cartella Drive in un unico PDF.

**Request body (JSON):**
```json
{
  "src": "https://drive.google.com/drive/folders/SOURCE_FOLDER_ID",
  "dst": "https://drive.google.com/drive/folders/DEST_FOLDER_ID",
  "output": "report_aprile_2026.pdf"
}
```

| Campo | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `src` | string | si | URL o ID cartella Drive sorgente |
| `dst` | string | si | URL o ID cartella Drive destinazione |
| `output` | string | no | Nome del PDF (default: `merged.pdf`) |

**Response (JSON):**
```json
{
  "id": "1xYz_AbCdEfGhIjKlMnOpQr",
  "name": "report_aprile_2026.pdf",
  "webViewLink": "https://drive.google.com/file/d/1xYz.../view"
}
```

### Configurazione nodo N8N

Nel workflow N8N aggiungi un nodo **HTTP Request**:

```
Method:       POST
URL:          http://python-utils:8000/gdrive-to-pdf
Content-Type: application/json
Body:
{
  "src":    "{{ $json.src_folder_url }}",
  "dst":    "{{ $json.dst_folder_url }}",
  "output": "{{ $json.output_name }}"
}
```

Il campo `webViewLink` nella risposta contiene il link diretto al PDF su Drive.

---

## Integrazione MCP (Claude Code)

Il MCP server usa il trasporto **stdio**: Claude Code avvia il processo e comunica via stdin/stdout.

### Configurazione `.mcp.json`

Crea un file `.mcp.json` nella root del progetto (o nella home di Claude Code):

```json
{
  "mcpServers": {
    "python-utils": {
      "command": "docker",
      "args": [
        "exec", "-i", "python-utils",
        "python", "/app/mcp_server.py"
      ],
      "env": {
        "GDRIVE_CREDENTIALS_FILE": "/app/credentials.json",
        "GDRIVE_TOKEN_FILE": "/app/token.json"
      }
    }
  }
}
```

> Il flag `-i` di `docker exec` è **obbligatorio** per mantenere stdin aperto (richiesto dal trasporto stdio MCP).

### Alternativa: esecuzione locale (senza Docker)

```json
{
  "mcpServers": {
    "python-utils": {
      "command": "python",
      "args": ["/path/to/repo/mcp_server.py"],
      "env": {
        "GDRIVE_CREDENTIALS_FILE": "/path/to/credentials.json",
        "GDRIVE_TOKEN_FILE": "/path/to/token.json"
      }
    }
  }
}
```

### Tool MCP disponibili

#### `gdrive_folder_to_pdf`

| Parametro | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `src` | string | si | URL o ID cartella Drive sorgente |
| `dst` | string | si | URL o ID cartella Drive destinazione |
| `output` | string | no | Nome del PDF (default: `merged.pdf`) |

**Esempio di utilizzo in Claude Code:**

```
Usa il tool gdrive_folder_to_pdf con:
  src = "https://drive.google.com/drive/folders/SOURCE_ID"
  dst = "https://drive.google.com/drive/folders/DEST_ID"
  output = "report.pdf"
```

**Risposta:**
```
PDF caricato con successo.
Link: https://drive.google.com/file/d/1xYz.../view
File ID: 1xYz_AbCdEfGhIjKlMnOpQr
Nome: report.pdf
```

---

## Sviluppo locale (senza Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Avvia il server HTTP
uvicorn api_server:app --reload --port 8000

# Avvia il MCP server (test manuale)
python mcp_server.py

# Esegui i test
pytest
```

Documentazione interattiva API: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Struttura del progetto

```
claude_py_experimental_repo/
├── scripts/
│   ├── __init__.py
│   └── gdrive_folder_to_pdf.py   # Conversione cartella Drive → PDF unificato
├── tests/
│   └── test_gdrive_folder_to_pdf.py
├── mcp_server.py                  # MCP server (stdio) per Claude Code
├── api_server.py                  # HTTP server (FastAPI) per N8N
├── Dockerfile                     # Immagine Docker unica
├── docker-compose.yml             # Orchestrazione container
├── pyproject.toml                 # Dipendenze e configurazione
├── .env.example                   # Template variabili d'ambiente
├── CLAUDE.md                      # Istruzioni per AI assistants
└── README.md                      # Questo file
```

---

## Aggiungere nuovi script

1. Crea `scripts/nome_script.py` con una funzione `run(...)` pubblica
2. Aggiungi il tool in `mcp_server.py` → `list_tools()` e `call_tool()`
3. Aggiungi l'endpoint in `api_server.py`
4. Aggiungi i test in `tests/`
5. Aggiorna la tabella "Scripts disponibili" in questo README
