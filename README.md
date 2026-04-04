# claude_py_experimental_repo

Script Python invocabili da **N8N** (HTTP POST) e **Claude Code** (MCP),
eseguiti in un container Docker sul VPS.

---

## Architettura

```
Il tuo PC  ──SSH──►  VPS Hostinger
                          │
                     docker compose
                          │
              ┌───────────┼───────────────┐
              │           │               │
           mariadb       n8n        claude-code
              │           │               │
              └───────────┘        docker exec -i
                                         │ (MCP stdio)
                                         ▼
                                   python-utils :8000
                                   ├── api_server.py   ◄── n8n HTTP POST
                                   ├── mcp_server.py   ◄── claude-code MCP
                                   └── scripts/        (condivisi)
```

---

## Come si lavora

**Tutto avviene sul VPS via SSH.** Dal tuo PC apri un terminale e fai SSH sul VPS.
Da lì, un solo comando avvia tutto: `docker compose up -d`.

L'unica eccezione è il token Google OAuth (vedi sotto), che richiede un browser una volta sola.

---

## Installazione

### Passo 1 — Sul VPS: clona il repo

```bash
git clone <repo-url> /opt/python-utils
cd /opt/python-utils
```

### Passo 2 — Sul VPS: crea il file .env

```bash
cp .env.example .env
nano .env
```

Compila questi valori:

```env
ANTHROPIC_API_KEY=sk-ant-...          # API key Anthropic
WORKSPACE_PATH=/opt/python-utils      # cartella del progetto sul VPS

MYSQL_ROOT_PASSWORD=scegli_password
MYSQL_PASSWORD=scegli_password
N8N_ENCRYPTION_KEY=stringa_random_32_caratteri
N8N_WEBHOOK_URL=https://tuodominio.com:5678
```

### Passo 3 — Google OAuth2: genera il token (una volta sola)

Questo passaggio richiede un browser ed è l'unico che **non** puoi fare
direttamente sul VPS. Hai due opzioni:

**Opzione A — Dal tuo PC in locale** (consigliata):

```bash
# Sul tuo PC (non sul VPS)
pip install google-auth-oauthlib google-api-python-client pypdf
python scripts/gdrive_folder_to_pdf.py \
  --src "URL_CARTELLA_SORGENTE" \
  --dst "URL_CARTELLA_DESTINAZIONE"
# Si apre il browser → autorizza → viene creato token.json

# Poi copia entrambi i file sul VPS
scp credentials.json token.json user@ip-vps:/opt/python-utils/
```

**Opzione B — Con port forwarding SSH** (tutto sul VPS):

```bash
# Dal tuo PC, apri un tunnel SSH
ssh -L 8085:localhost:8085 user@ip-vps

# Poi sul VPS esegui lo script: il browser si aprirà sul tuo PC
python scripts/gdrive_folder_to_pdf.py --src "..." --dst "..."
```

> Dopo questa operazione `credentials.json` e `token.json` rimangono sul VPS
> e non servono più interventi manuali. Il token si rinnova da solo.

### Passo 4 — Sul VPS: avvia tutto

```bash
docker compose up -d
```

Fine. I container si avviano nell'ordine corretto grazie ai `depends_on`.

### Passo 5 — Verifica

```bash
docker compose ps          # tutti i container devono essere "running"
curl http://localhost:8000/health   # → {"status":"ok"}
```

---

## Aggiornare il codice

Quando aggiungi nuovi script al repo:

```bash
# Sul VPS
cd /opt/python-utils
git pull
docker compose up -d --build python-utils   # rebuild solo del container Python
```

---

## Usare Claude Code

```bash
# Apri una sessione interattiva (dal VPS via SSH)
docker exec -it claude-code claude
```

Claude Code si avvia con i tool MCP già configurati e pronti.

---

## Scripts disponibili

| Script | Endpoint HTTP | Tool MCP | Descrizione |
|---|---|---|---|
| `scripts/gdrive_folder_to_pdf.py` | `POST /gdrive-to-pdf` | `gdrive_folder_to_pdf` | Converte cartella Drive → PDF |

---

## API HTTP (per N8N)

Documentazione interattiva Swagger: `http://ip-vps:8000/docs`

### `POST /gdrive-to-pdf`

**Request:**
```json
{
  "src": "https://drive.google.com/drive/folders/SOURCE_ID",
  "dst": "https://drive.google.com/drive/folders/DEST_ID",
  "output": "report.pdf"
}
```

**Response:**
```json
{
  "id": "1xYz...",
  "name": "report.pdf",
  "webViewLink": "https://drive.google.com/file/d/1xYz.../view"
}
```

### Nodo N8N — HTTP Request

```
Method:  POST
URL:     http://python-utils:8000/gdrive-to-pdf
Body:    { "src": "...", "dst": "...", "output": "..." }
```

N8N e python-utils sono sulla stessa rete Docker (`vps-net`) e si vedono per nome.

---

## Tool MCP (per Claude Code)

### `gdrive_folder_to_pdf`

| Parametro | Obbligatorio | Default | Descrizione |
|---|---|---|---|
| `src` | si | — | URL cartella Drive sorgente |
| `dst` | si | — | URL cartella Drive destinazione |
| `output` | no | `merged.pdf` | Nome del PDF di output |

---

## Aggiungere nuovi script

1. Crea `scripts/nuovo_script.py` con funzione `run(...)`
2. Registra il tool in `mcp_server.py`
3. Aggiungi l'endpoint in `api_server.py`
4. Aggiorna la tabella "Scripts disponibili" qui sopra
5. `git push` → sul VPS `git pull && docker compose up -d --build python-utils`

---

## Struttura del progetto

```
claude_py_experimental_repo/
├── scripts/
│   ├── __init__.py
│   └── gdrive_folder_to_pdf.py
├── tests/
│   └── test_gdrive_folder_to_pdf.py
├── docker/
│   └── claude-code/
│       ├── Dockerfile
│       └── .mcp.json.example
├── mcp_server.py
├── api_server.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```
