# CLAUDE.md

This file provides guidance to AI assistants (Claude Code and similar tools) working in this repository.

## Repository Overview

**Purpose**: An experimental Python repository for exploring Claude Code capabilities and Python development patterns.

- **Language**: Python
- **Status**: Early-stage / experimental
- **Description**: "Esperimenti con Claude code in Python" — experiments with Claude Code in Python

## Repository Structure

```
claude_py_experimental_repo/
├── .gitignore       # Comprehensive Python gitignore
├── README.md        # Project description
└── CLAUDE.md        # This file
```

No source code exists yet. As the project grows, expect directories such as:
- `src/` or a top-level package directory for application code
- `tests/` for test files
- `pyproject.toml` or `setup.py` for packaging and dependencies

## Git Workflow

- **Main branch**: `main` — stable, reviewed code only
- **Development branches**: `claude/<description>-<id>` for AI-driven work; feature branches for human-driven work
- **Commit signing**: Enabled via SSH key; commits are signed automatically
- **Remote**: `http://local_proxy@127.0.0.1:37341/git/nifritz/claude_py_experimental_repo`

### Branch conventions

- Always develop on the designated feature branch, never push directly to `main`
- Branch names for Claude-initiated work follow the pattern `claude/<short-description>-<id>`
- Push with: `git push -u origin <branch-name>`

## Python Conventions

Since no source code exists yet, follow these conventions when adding code:

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

### Adding new experiments
1. Create a clearly named Python file or package
2. Add a corresponding test file under `tests/`
3. Update `README.md` to document what the experiment does

### When setting up the project for the first time
1. Create `pyproject.toml` with project metadata and dependencies
2. Initialize a virtual environment: `python -m venv .venv` or `uv venv`
3. Install dependencies: `pip install -e .[dev]` or `uv sync`
4. Configure Ruff and pytest in `pyproject.toml`

### Running code
Until a proper entry point exists, run scripts directly: `python <script.py>`

## Notes for AI Assistants

- This is an experimental repo — expect code to change frequently
- Prefer editing existing files over creating new ones unless a new file is clearly needed
- Keep experiments self-contained; avoid cross-dependencies between unrelated experiments
- Do not add unnecessary abstractions — keep code simple and readable
- Do not commit secrets, credentials, or `.env` files
- Always work on the designated feature branch, not `main`
- When in doubt about scope, ask before making large structural changes
