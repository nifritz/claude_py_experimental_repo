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

### Tool: `merge_pdfs`

| Parametro | Obbligatorio | Descrizione |
|---|---|---|
| `files` | si | Lista di percorsi file PDF nel workspace (in ordine) |
| `output` | si | Percorso del PDF di output |

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

1. Crea `scripts/nome_script.py` con la logica pura (nessuna I/O Google)
2. Aggiungi l'endpoint in `api_server.py`
3. Aggiungi il tool in `mcp_server.py`
4. `git push` → deploy automatico

### Script disponibili

| Script | Endpoint | Tool MCP | Descrizione |
|---|---|---|---|
| `scripts/merge_pdfs.py` | `POST /merge-pdfs` | `merge_pdfs` | Unisce PDF binari in input |

---

## Struttura

```
python-utils/
├── scripts/
│   ├── __init__.py
│   └── merge_pdfs.py           ← logica pura (no auth)
├── docker/
│   ├── claude-code/
│   │   ├── Dockerfile
│   │   └── .mcp.json.example
│   └── webhook/
│       ├── Dockerfile
│       └── server.py
├── api_server.py               ← HTTP server per N8N
├── mcp_server.py               ← MCP server per Claude Code
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```
