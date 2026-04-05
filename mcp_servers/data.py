#!/usr/bin/env python3
"""
MCP server — Data

Tool per la trasformazione e analisi di dati strutturati (CSV, JSON, ecc.).
Ogni script in scripts/ che lavora con dati va esposto qui.

Avvio (gestito da Claude Code tramite .mcp.json):
    python mcp_servers/data.py

--- COME AGGIUNGERE UN TOOL ---
1. Crea scripts/nome_script.py con la logica pura (no I/O esterno)
2. Importalo qui
3. Aggiungi il Tool in list_tools()
4. Gestisci la chiamata in call_tool()
5. Aggiungi l'endpoint HTTP in api_server.py se serve anche a N8N
"""

import asyncio
import logging

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# from scripts.csv_to_json import convert     # <-- decommentare quando implementato
# from scripts.summarize_table import summarize  # <-- decommentare quando implementato

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

server = Server("data")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        # -----------------------------------------------------------------
        # TODO: implementare scripts/csv_to_json.py e decommentare
        # -----------------------------------------------------------------
        # types.Tool(
        #     name="csv_to_json",
        #     description="Converte un file CSV in JSON.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "file":      {"type": "string", "description": "Percorso file CSV"},
        #             "output":    {"type": "string", "description": "Percorso file JSON output"},
        #             "delimiter": {"type": "string", "description": "Separatore (default: ,)"},
        #         },
        #         "required": ["file", "output"],
        #     },
        # ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # if name == "csv_to_json":
    #     ...
    raise ValueError(f"Tool sconosciuto: {name!r}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
