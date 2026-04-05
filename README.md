# python-utils

Script Python eseguiti in un container Docker, invocabili da **N8N** (HTTP POST)
e da **Claude Code** (MCP).

**Principio:** Python non sa nulla di Google Drive. N8N (già autenticato) scarica i file,
li invia qui come binari, riceve il risultato e lo ricarica su Drive.

---

## Architettura

```
dockercomposepath/
├── docker-compose.yml        ← il TUO compose esistente (n8n, mariadb, ecc.)
├── .env                      ← il TUO .env (aggiungi 3 variabili)
└── python-utils/             ← questo repo (git clone)
    ├── docker-compose.yml    ← compose dei 3 nuovi container
    ├── Dockerfile
    ├── api_server.py
    ├── mcp_server.py
    └── scripts/
```

```
N8N  ──── POST multipart ────►  python-utils:8000  (file in → PDF out)
                                      │
Claude Code  ── docker exec ──►       │ (stessa immagine)
                                      │
GitHub  ──── POST :9000 ──────►  webhook:9000
                                      │
                                  git pull + docker compose up --build
```

I 3 container si agganciano alla rete Docker esistente (la stessa di n8n, mariadb)
e si vedono per nome servizio — esattamente come mariadb è già raggiungibile da n8n.

---

## Come funziona Docker

### `build` costruisce un'immagine, non è un link alla cartella

`build: .` non punta alla cartella live. Costruisce un'immagine autonoma:
1. Scarica `python:3.11-slim`
2. Esegue `pip install`
3. Copia il codice dentro l'immagine

Dopo il build, il container non dipende più dal filesystem del VPS.
Python non viene riscaricato ai riavvii — si usa l'immagine già salvata.

```
Primo avvio (--build):  scarica Python + installa + copia → salva immagine → avvia
Riavvii successivi:     usa immagine salvata → avvia  (veloce, zero download)
Dopo git pull (--build): Python in cache → ricopia solo il codice → avvia
```

### Nessun volume per credenziali

python-utils non monta nessun file segreto. Riceve dati da N8N via HTTP e risponde
con HTTP. Zero gestione token.

---

## Installazione

### 1 — Trova la rete Docker esistente

```bash
docker network ls
# oppure
docker inspect n8n | grep -A5 '"Networks"'
```

Prendi nota del nome (es. `hostinger_default`).

### 2 — Clona il repo

```bash
cd dockercomposepath/
git clone <repo-url> python-utils
```

### 3 — Crea `.env`

```bash
cp python-utils/.env.example python-utils/.env
nano python-utils/.env
```

```env
DOCKER_NETWORK_NAME=nome_rete_trovato_al_passo_1
ANTHROPIC_API_KEY=sk-ant-...
DEPLOY_SECRET=stringa_casuale_lunga_almeno_32_caratteri
```

### 4 — Avvia

```bash
# Da dockercomposepath/
docker compose -f python-utils/docker-compose.yml up -d --build
```

### 5 — Verifica

```bash
docker compose -f python-utils/docker-compose.yml ps
# python-utils → healthy,  claude-code → running,  webhook → running

docker exec n8n wget -qO- http://python-utils:8000/health
# → {"status":"ok"}
```

---

## API HTTP (per N8N)

Documentazione interattiva (Swagger): `ssh -L 8000:localhost:8000 user@ip-vps`
poi apri `http://localhost:8000/docs`.

---

### `GET /health`

```
→ {"status": "ok"}
```

---

### `POST /merge-pdfs`

Unisce più file PDF in un unico PDF.

**Request:** `multipart/form-data`, campo `files` (uno o più file PDF).

**Response:** `application/pdf` — il PDF unito come file binario.

Query param opzionale: `?output=nome.pdf` (nome nel header Content-Disposition).

---

**Flusso N8N completo — Google Drive → PDF unito → Google Drive:**

```
[Trigger]
    │
    ▼
[Google Drive] List Files — source folder ID
    │  restituisce lista file
    ▼
[Loop] per ogni file:
    └─► [Google Drive] Download / Export as PDF
           (per Google Docs/Sheets/Slides usa "Export" con mimeType application/pdf)
    │
    ▼  (tutti i file PDF scaricati come binary items)
[HTTP Request]
    Method:       POST
    URL:          http://python-utils:8000/merge-pdfs?output=report.pdf
    Body:         Form-Data  →  files: {{ $binary.data }}  (tutti i file in loop)
    │
    ▼  riceve: file PDF binario
[Google Drive] Upload File — destination folder ID
```

> N8N gestisce login Google, download, upload. Python riceve byte, restituisce byte.

---

## Claude Code (MCP)

```bash
docker exec -it claude-code claude
```

### Filosofia: un server MCP per dominio

Non esiste un unico server MCP con tutti gli script dentro.
Ogni server copre un dominio coerente ed è un processo stdio separato.

```
mcp_servers/
├── pdf.py      ← tutto ciò che riguarda PDF   (merge, split, compress…)
├── images.py   ← tutto ciò che riguarda immagini (resize, convert…)
└── data.py     ← tutto ciò che riguarda dati  (CSV, JSON, tabelle…)
```

Quando aggiungi uno script nuovo, la prima domanda è:
**"In quale server va questo tool?"** — non "aggiungo al server esistente".

Se nessuno è adatto, crei `mcp_servers/nuovo_dominio.py` e aggiungi
l'entry in `.mcp.json`.

```json
// .mcp.json — ogni server è una entry separata
{
  "mcpServers": {
    "pdf":    { "command": "docker", "args": ["exec", "-i", "python-utils", "python", "/app/mcp_servers/pdf.py"] },
    "images": { "command": "docker", "args": ["exec", "-i", "python-utils", "python", "/app/mcp_servers/images.py"] },
    "data":   { "command": "docker", "args": ["exec", "-i", "python-utils", "python", "/app/mcp_servers/data.py"] }
  }
}
```

### Server e tool disponibili

#### `pdf` — `mcp_servers/pdf.py`

| Tool | Descrizione |
|---|---|
| `merge_pdfs` | Unisce PDF locali in un unico file |

#### `images` — `mcp_servers/images.py`

Scheletro pronto. Aggiungi tool commentando/decommentando in `list_tools()`.

#### `data` — `mcp_servers/data.py`

Scheletro pronto. Aggiungi tool commentando/decommentando in `list_tools()`.

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
docker compose -f python-utils/docker-compose.yml up -d --build python-utils
```

---

## Aggiungere nuovi script

### Checklist

1. **Crea** `scripts/nome_script.py` — logica pura, no I/O esterno, no auth
2. **Scegli il server MCP** giusto per dominio (`mcp_servers/pdf.py`, `images.py`, `data.py`)
   — se nessuno è adatto, crea `mcp_servers/nuovo.py` e aggiungilo a `.mcp.json`
3. **Importa e registra** il tool in quel server (segui il pattern commentato negli scheletri)
4. **Aggiungi l'endpoint** in `api_server.py` se lo script serve anche a N8N
5. `git push` → deploy automatico

### Mappa script → server MCP → endpoint HTTP

| Script | Server MCP | Endpoint HTTP | Descrizione |
|---|---|---|---|
| `scripts/merge_pdfs.py` | `mcp_servers/pdf.py` | `POST /merge-pdfs` | Unisce PDF |
| *(scheletro)* | `mcp_servers/images.py` | — | Operazioni immagini |
| *(scheletro)* | `mcp_servers/data.py` | — | Trasformazione dati |

---

## Struttura

```
python-utils/
├── scripts/                    ← logica pura (no auth, no I/O esterno)
│   ├── __init__.py
│   └── merge_pdfs.py
├── mcp_servers/                ← un server per dominio
│   ├── __init__.py
│   ├── pdf.py                  ← tool PDF (merge_pdfs, …)
│   ├── images.py               ← tool immagini (scheletro)
│   └── data.py                 ← tool dati (scheletro)
├── docker/
│   ├── claude-code/
│   │   ├── Dockerfile
│   │   └── .mcp.json.example   ← un entry per server MCP
│   └── webhook/
│       ├── Dockerfile
│       └── server.py
├── api_server.py               ← HTTP server per N8N
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```
