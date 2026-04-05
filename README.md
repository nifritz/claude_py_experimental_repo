# python-utils

Script Python eseguiti in un container Docker, invocabili da **N8N** (HTTP POST)
e da **Claude Code** (MCP). Vive come sottocartella dello stack Docker esistente.

---

## Architettura

```
dockercomposepath/
├── docker-compose.yml        ← il TUO compose esistente (n8n, mariadb, ecc.)
├── .env                      ← il TUO .env (aggiungi 3 variabili)
└── python-utils/             ← questo repo (git clone)
    ├── docker-compose.yml    ← compose dei 3 nuovi container
    ├── credentials.json      ← copiato da te (una volta sola)
    ├── token.json            ← generato una volta, poi aggiornato da N8N
    ├── Dockerfile
    ├── api_server.py
    ├── mcp_server.py
    └── scripts/
```

I 3 nuovi container si agganciano alla rete Docker già esistente (quella di n8n,
mariadb, ecc.) e si vedono tra loro per nome servizio.

```
N8N  ──────── HTTP POST ──────►  python-utils:8000
                                      │
Claude Code  ─ docker exec -i ──►     │ (stessa immagine)
                                      │
GitHub  ────── POST :9000 ──────►  webhook:9000
                                      │
                                  git pull + docker compose up --build
```

---

## Come funziona Docker (leggilo se sei nuovo)

### Il comando `build` costruisce una vera immagine

`build: .` nel docker-compose non è un puntamento alla cartella. È un'istruzione:
"costruisci un'immagine partendo dal Dockerfile in quella cartella".

Il Dockerfile fa:
1. Scarica `python:3.11-slim` da Docker Hub → Python installato qui
2. Esegue `pip install` → librerie installate dentro l'immagine
3. Copia il codice dentro l'immagine

Il risultato è un'immagine autonoma salvata localmente sul VPS.
Dopo il build, il container non dipende più dalla cartella del repo.

### Python non viene riscaricato a ogni riavvio

L'immagine viene costruita una sola volta. Riavvii, reboot del VPS,
`docker compose restart` riutilizzano sempre l'immagine già salvata.
Nessun download.

Docker usa una cache a layer: se `FROM python:3.11-slim` non cambia
tra un build e l'altro, quel layer viene riusato automaticamente.

```
Primo avvio (--build):
  scarica Python + pip install + copia codice → salva immagine → avvia

Riavvii successivi:
  usa immagine già salvata → avvia   ← veloce, nessun download

Dopo git pull (--build):
  layer Python in cache → ricopia solo il codice → avvia
```

### I volumi sono i soli file fuori dal container

Tutto il codice è dentro l'immagine. I soli file montati dall'esterno sono
quelli che contengono segreti o dati che cambiano a runtime:

```yaml
volumes:
  - ./credentials.json:/app/credentials.json:ro   # client secret Google
  - ./token.json:/app/token.json                   # token OAuth2 (aggiornato da N8N)
```

---

## Installazione

### Passo 1 — Trova il nome della rete Docker esistente

```bash
ssh user@ip-vps
docker network ls
```

Cerca la rete a cui sono collegati n8n e mariadb. Di solito ha il formato
`nomecartella_default`. Se non sei sicuro:

```bash
docker inspect n8n | grep -A5 '"Networks"'
# oppure
docker inspect mariadb | grep -A5 '"Networks"'
```

Prendi nota del nome: ti servirà nel passo 3.

### Passo 2 — Clona il repo come sottocartella

```bash
ssh user@ip-vps
cd dockercomposepath/          # la cartella dove hai già il tuo docker-compose.yml
git clone <repo-url> python-utils
```

### Passo 3 — Crea il file .env

```bash
cp python-utils/.env.example python-utils/.env
nano python-utils/.env
```

Compila i 3 valori:

```env
DOCKER_NETWORK_NAME=nome_rete_trovato_al_passo_1
ANTHROPIC_API_KEY=sk-ant-...
DEPLOY_SECRET=stringa_casuale_lunga_almeno_32_caratteri
```

### Passo 4 — Copia credentials.json

Scarica `credentials.json` da Google Cloud Console (OAuth 2.0 client secret)
e copialo sul VPS:

```bash
# Dal tuo PC
scp credentials.json user@ip-vps:dockercomposepath/python-utils/
```

Questo file non cambia mai. Non va committato.

### Passo 5 — Genera token.json (solo la prima volta)

Il token OAuth richiede un browser la prima volta. Fallo dal tuo PC:

```bash
# Sul tuo PC
pip install google-auth-oauthlib google-api-python-client pypdf
python python-utils/scripts/gdrive_folder_to_pdf.py \
  --src "URL_CARTELLA_QUALSIASI" --dst "URL_CARTELLA_QUALSIASI"
# Si apre il browser → accedi → token.json viene creato

# Copia sul VPS
scp token.json user@ip-vps:dockercomposepath/python-utils/
```

Da quel momento **N8N gestisce il rinnovo** del token (vedi sezione dedicata).

### Passo 6 — Avvia i container

```bash
# Da dockercomposepath/
docker compose -f python-utils/docker-compose.yml up -d --build
```

### Passo 7 — Verifica

```bash
docker compose -f python-utils/docker-compose.yml ps
# python-utils → healthy
# claude-code  → running
# webhook      → running

# Testa l'API dall'interno della rete (come fa N8N)
docker exec n8n wget -qO- http://python-utils:8000/health
# → {"status":"ok"}
```

---

## Aggiornare il codice

### Manuale

```bash
ssh user@ip-vps
cd dockercomposepath/python-utils
git pull
cd ..
docker compose -f python-utils/docker-compose.yml up -d --build python-utils
```

### Automatico (push → deploy)

Ogni `git push` triggera automaticamente `git pull` + rebuild sul VPS.

**Configurazione GitHub:**

1. Repo → Settings → Webhooks → Add webhook
2. Payload URL: `http://ip-vps:9000/deploy`
3. Content type: `application/json`
4. Secret: il valore di `DEPLOY_SECRET` nel tuo `.env`
5. Which events: solo **Push**

Il container `webhook` ha la propria immagine separata e non viene mai
coinvolto nel rebuild — rimane sempre attivo durante gli aggiornamenti.

---

## API HTTP (per N8N)

Tutti gli endpoint sono raggiungibili da N8N come `http://python-utils:8000`.
Nessuna porta esposta all'esterno del VPS.

Documentazione interattiva (Swagger): apri una sessione SSH con port-forward
`ssh -L 8000:localhost:8000 user@ip-vps` poi vai su `http://localhost:8000/docs`.

---

### `GET /health`

```
GET http://python-utils:8000/health
→ {"status": "ok"}
```

---

### `POST /gdrive-to-pdf`

Converte tutti i file di una cartella Google Drive in un unico PDF e lo
carica nella cartella di destinazione.

**Request:**
```json
{
  "src": "https://drive.google.com/drive/folders/SOURCE_FOLDER_ID",
  "dst": "https://drive.google.com/drive/folders/DEST_FOLDER_ID",
  "output": "report_aprile_2026.pdf"
}
```

| Campo | Obbligatorio | Default | Descrizione |
|---|---|---|---|
| `src` | si | — | URL o ID cartella Drive sorgente |
| `dst` | si | — | URL o ID cartella Drive destinazione |
| `output` | no | `merged.pdf` | Nome del PDF di output |

**Formato supportati nella cartella sorgente:**
Google Docs, Google Sheets, Google Slides, Google Drawings, file PDF.
Gli altri formati vengono ignorati con un warning nel log.

**Response:**
```json
{
  "id": "1xYz_AbCdEfGhIjKlMnOpQr",
  "name": "report_aprile_2026.pdf",
  "webViewLink": "https://drive.google.com/file/d/1xYz.../view"
}
```

**Nodo N8N — HTTP Request:**
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

---

### `POST /auth/token` — Rinnovo token Google (chiamato da N8N)

Aggiorna il file `token.json` con il nuovo access token ottenuto da Google.
Da integrare nel workflow N8N che gestisce già i token di Shopify e Meta.

**Flusso N8N:**

```
[Schedule / Trigger]
        │
        ▼
[HTTP Request] POST https://oauth2.googleapis.com/token
  Body:
    grant_type=refresh_token
    client_id={{$credentials.client_id}}
    client_secret={{$credentials.client_secret}}
    refresh_token={{$credentials.refresh_token}}
        │
        ▼ riceve: access_token, expires_in, ...
        │
        ▼
[HTTP Request] POST http://python-utils:8000/auth/token
  Body:
    {
      "access_token":  "{{ $json.access_token }}",
      "refresh_token": "IL_TUO_REFRESH_TOKEN",
      "client_id":     "IL_TUO_CLIENT_ID",
      "client_secret": "IL_TUO_CLIENT_SECRET",
      "expiry":        "{{ /* calcola: now + expires_in */ }}"
    }
```

**Response:**
```json
{"status": "ok"}
```

> `refresh_token`, `client_id` e `client_secret` non cambiano mai:
> salvali come credenziali in N8N e usale nelle espressioni.

---

## Claude Code (MCP)

Il container `claude-code` ha il Docker socket montato e la config MCP
già presente. Avvia una sessione interattiva con:

```bash
docker exec -it claude-code claude
```

I tool MCP sono disponibili immediatamente nella sessione.

### Tool disponibili

#### `gdrive_folder_to_pdf`

| Parametro | Obbligatorio | Default | Descrizione |
|---|---|---|---|
| `src` | si | — | URL cartella Drive sorgente |
| `dst` | si | — | URL cartella Drive destinazione |
| `output` | no | `merged.pdf` | Nome del PDF di output |

---

## Aggiungere nuovi script

Per aggiungere un nuovo script al sistema:

1. **Crea** `scripts/nome_script.py` con una funzione `run(...)` pubblica
2. **Registra il tool MCP** in `mcp_server.py`:
   - Aggiungi il tool in `list_tools()`
   - Gestisci la chiamata in `call_tool()`
3. **Aggiungi l'endpoint** in `api_server.py`
4. **Aggiorna** la tabella "Scripts disponibili" qui sotto
5. `git push` → deploy automatico via webhook

### Scripts disponibili

| Script | Endpoint HTTP | Tool MCP | Descrizione |
|---|---|---|---|
| `scripts/gdrive_folder_to_pdf.py` | `POST /gdrive-to-pdf` | `gdrive_folder_to_pdf` | Cartella Google Drive → PDF unico |

---

## Struttura del progetto

```
python-utils/
├── scripts/
│   ├── __init__.py
│   └── gdrive_folder_to_pdf.py   ← logica script
├── docker/
│   ├── claude-code/
│   │   ├── Dockerfile
│   │   └── .mcp.json.example     ← config MCP (montata nel container)
│   └── webhook/
│       ├── Dockerfile
│       └── server.py             ← webhook deploy
├── api_server.py                 ← HTTP server per N8N
├── mcp_server.py                 ← MCP server per Claude Code
├── Dockerfile                    ← immagine python-utils
├── docker-compose.yml            ← 3 container (python-utils, claude-code, webhook)
├── pyproject.toml                ← dipendenze Python
├── .env.example                  ← template variabili d'ambiente
└── README.md
```
