# CLAUDE.md

This file provides guidance to AI assistants (Claude Code and similar tools) working in this repository.

## Repository Overview

**Purpose**: Python backend che espone tool HTTP (via FastAPI) consumati da workflow N8N.

- **Language**: Python
- **Status**: Attivo / in crescita
- **Utilizzo principale**: N8N chiama endpoint specifici di `api_server.py` per operazioni su immagini, PDF e altro

## Repository Structure

```
claude_py_experimental_repo/
├── api_server.py          # FastAPI app — entry point principale, endpoint chiamati da N8N
├── scripts/               # Logica pura dei tool (importata da api_server.py)
│   ├── merge_pdfs.py
│   ├── split_grid.py
│   └── test_hello.py
├── mcp_servers/           # Scheletro MCP (completato ma non utilizzato al momento)
│   ├── data.py
│   ├── images.py
│   └── pdf.py
├── docker/
│   ├── webhook/
│   │   └── server.py      # Webhook server per deploy automatico — NON TOCCARE (vedi sotto)
│   └── claude-code/       # Dockerfile per ambiente Claude Code
├── Dockerfile             # Build dell'api_server
├── pyproject.toml         # Dipendenze e configurazione progetto
└── .env.example           # Variabili d'ambiente richieste
```

## Git Workflow

- **Default**: lavora direttamente su `main`. Per lavoro nuovo (nuovo endpoint, nuovo script, nuova feature) committa e pusha su `main` senza creare branch e senza chiedere conferma.
- **Commit signing**: Enabled via SSH key; commits are signed automatically
- **Remote**: `http://local_proxy@127.0.0.1:37341/git/nifritz/claude_py_experimental_repo`

### Quando usare un branch (eccezione, non regola)

Crea un branch `claude/<short-description>-<id>` **solo** se il lavoro è rischioso, e in particolare quando:

- Modifica/rifattorizza codice o endpoint **esistenti** che già funzionano (rischio di rompere consumi N8N in produzione)
- Tocca infra di deploy o file critici (es. `docker/webhook/server.py` — vedi sotto)
- È un cambiamento ampio/strutturale di cui non si è sicuri
- L'utente lo chiede esplicitamente

In questi casi: branch → push con `git push -u origin <branch-name>` → PR per review.

Per tutto il resto (roba nuova, additiva, a basso rischio): direttamente su `main`.

## Python Conventions

### Style
- Follow [PEP 8](https://peps.python.org/pep-0008/) for formatting
- Use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting (the gitignore already accounts for its cache)
- Prefer `snake_case` for variables and functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants

### Project setup (when initializing)
- Use `pyproject.toml` as the single source of truth for project metadata, dependencies, and tool configuration
- Use a virtual environment: `.venv/` (already gitignored)
- Preferred package manager: `uv` or `pip`; `uv.lock` can optionally be committed

### Testing
- Use `pytest` for tests (already gitignored: `.pytest_cache/`, `htmlcov/`, `.coverage`)
- Place tests under `tests/` mirroring the source layout
- Run tests with: `pytest`

### Type checking
- Use type hints on all public function signatures
- `mypy` or `pyright` for static analysis (`.mypy_cache/` already gitignored)

## Environment

- Do not commit `.env` files (already gitignored)
- Use `.env` locally for secrets and environment variables
- Document required environment variables in README or a `.env.example` file

## Working with This Repository

### Aggiungere un nuovo tool/endpoint
1. Creare il file logica in `scripts/<nome>.py` (funzione pura, nessun riferimento HTTP)
2. Importarlo e registrare l'endpoint in `api_server.py`
3. **Aggiornare `pyproject.toml`** se lo script richiede nuove librerie — è la fonte di verità per le dipendenze
4. Aggiornare `README.md` per documentare l'endpoint

### Setup iniziale
1. Inizializzare un virtual environment: `python -m venv .venv` o `uv venv`
2. Installare dipendenze: `pip install -e .[dev]` o `uv sync`

### Running code
```bash
uvicorn api_server:app --reload
```

## Notes for AI Assistants

- Prefer editing existing files over creating new ones unless a new file is clearly needed
- Do not add unnecessary abstractions — keep code simple and readable
- Do not commit secrets, credentials, or `.env` files
- Default: lavora e pusha direttamente su `main` (vedi Git Workflow). Branch solo per lavoro rischioso o su codice esistente
- When in doubt about scope, ask before making large structural changes
- When adding a new script that requires new libraries, always update `pyproject.toml` accordingly

### MCP servers
La cartella `mcp_servers/` contiene uno scheletro MCP completato ma **non attualmente utilizzato**. Non sviluppare ulteriormente questa parte salvo indicazione esplicita.

### N8N integration
Il flusso principale è: **N8N → POST endpoint su `api_server.py` → funzione in `scripts/`**. Ogni nuovo tool deve seguire questo pattern.

### ⚠️ NON toccare `docker/webhook/server.py`
Questo file gestisce il deploy automatico via webhook su Hostinger. In passato un bug causava la creazione di due istanze Docker Compose separate, mandando in crash il pannello web di Hostinger. Il problema era l'assenza del nome progetto esplicito nel comando `docker compose`. La fix è stata aggiungere `-p automazioni` e `-f /compose/docker-compose.yml` esplicitamente. Il file ora funziona correttamente — **non modificarlo** senza istruzioni esplicite.
