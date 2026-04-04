# claude_py_experimental_repo

Esperimenti con Claude Code in Python.

> Questo repository contiene script Python eseguibili all'interno di un container Docker,
> invocabili da **N8N** (via HTTP POST) e da **Claude Code** (via MCP).

---

## Scripts

### `scripts/gdrive_folder_to_pdf.py`

Converte tutti i file in una cartella Google Drive in un unico PDF unificato
e lo carica in un'altra cartella Drive.

**File supportati:**
- Google Docs → PDF (export nativo)
- Google Sheets → PDF
- Google Slides → PDF
- Google Drawings → PDF
- File `.pdf` già presenti nella cartella (download diretto)

I file vengono ordinati per nome prima di essere uniti.

#### Setup credenziali Google

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un progetto e abilita le API: **Google Drive API**
3. Crea credenziali **OAuth 2.0** → tipo *Web application* o *Desktop app*
4. Scarica il file JSON e salvalo come `credentials.json` nella root del progetto
5. Al primo avvio lo script aprirà il browser per l'autorizzazione e salverà `token.json`

```bash
# Copia il file di esempio e personalizzalo
cp .env.example .env
```

#### Installazione dipendenze

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

oppure con `uv`:

```bash
uv venv && uv sync
```

#### Utilizzo da CLI

```bash
python scripts/gdrive_folder_to_pdf.py \
  --src "https://drive.google.com/drive/folders/SOURCE_FOLDER_ID" \
  --dst "https://drive.google.com/drive/folders/DEST_FOLDER_ID" \
  --output "report_aprile_2026.pdf" \
  --credentials credentials.json \
  --token token.json
```

Lo script stampa su stdout il link Google Drive del PDF caricato.

**Parametri:**

| Parametro | Descrizione | Default |
|---|---|---|
| `--src` | URL o ID cartella sorgente Drive | obbligatorio |
| `--dst` | URL o ID cartella destinazione Drive | obbligatorio |
| `--output` | Nome del PDF di output | `merged.pdf` |
| `--credentials` | Path al file `credentials.json` | `credentials.json` |
| `--token` | Path al file `token.json` | `token.json` |

---

## Come chiamare gli script

### Da N8N (HTTP POST via container Python)

Esponi lo script tramite un semplice HTTP server (es. Flask) nel container Python,
oppure eseguilo direttamente via N8N **Execute Command** node se i container sono
sullo stesso Docker network.

#### Opzione A — Execute Command node (stesso network Docker)

Nel nodo **Execute Command** di N8N:

```
Command: python /app/scripts/gdrive_folder_to_pdf.py
Arguments:
  --src={{ $json.src_url }}
  --dst={{ $json.dst_url }}
  --output={{ $json.output_name }}
  --credentials=/app/credentials.json
  --token=/app/token.json
```

#### Opzione B — HTTP POST con wrapper Flask

Aggiungi un endpoint Flask al container Python:

```python
# server.py (esempio minimo)
from flask import Flask, request, jsonify
from scripts.gdrive_folder_to_pdf import run

app = Flask(__name__)

@app.post("/gdrive-to-pdf")
def gdrive_to_pdf():
    data = request.json
    result = run(
        src_url=data["src"],
        dst_url=data["dst"],
        output_name=data.get("output", "merged.pdf"),
        credentials_file="/app/credentials.json",
        token_file="/app/token.json",
    )
    return jsonify(result)
```

Chiamata da N8N con nodo **HTTP Request**:

```
Method: POST
URL: http://python-container:5000/gdrive-to-pdf
Body (JSON):
{
  "src": "https://drive.google.com/drive/folders/SOURCE_ID",
  "dst": "https://drive.google.com/drive/folders/DEST_ID",
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

---

### Da Claude Code (via MCP)

Se il container Python espone un MCP server, Claude Code può chiamare lo script
come tool. Esempio di chiamata diretta in sessione Claude Code:

```
Usa lo script gdrive_folder_to_pdf con:
  src = "https://drive.google.com/drive/folders/SOURCE_ID"
  dst = "https://drive.google.com/drive/folders/DEST_ID"
  output = "report_aprile.pdf"
```

Claude Code eseguirà internamente:

```python
from scripts.gdrive_folder_to_pdf import run

result = run(
    src_url="https://drive.google.com/drive/folders/SOURCE_ID",
    dst_url="https://drive.google.com/drive/folders/DEST_ID",
    output_name="report_aprile.pdf",
    credentials_file="/app/credentials.json",
    token_file="/app/token.json",
)
print(result["webViewLink"])
```

---

## Testing

```bash
pytest
```

---

## Struttura del progetto

```
claude_py_experimental_repo/
├── scripts/
│   └── gdrive_folder_to_pdf.py   # Conversione cartella Drive → PDF unificato
├── tests/
│   └── test_gdrive_folder_to_pdf.py
├── .env.example                   # Template variabili d'ambiente
├── pyproject.toml                 # Dipendenze e configurazione
├── CLAUDE.md                      # Istruzioni per AI assistants
└── README.md                      # Questo file
```
