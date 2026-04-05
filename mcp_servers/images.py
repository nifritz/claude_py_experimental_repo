#!/usr/bin/env python3
"""
MCP server — Images

Tool per la manipolazione di immagini.
Ogni script in scripts/ che lavora con immagini va esposto qui.

Avvio (gestito da Claude Code tramite .mcp.json):
    python mcp_servers/images.py

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

# from scripts.resize_image import resize     # <-- decommentare quando implementato
# from scripts.convert_image import convert   # <-- decommentare quando implementato

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

server = Server("images")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        # -----------------------------------------------------------------
        # TODO: implementare scripts/resize_image.py e decommentare
        # -----------------------------------------------------------------
        # types.Tool(
        #     name="resize_image",
        #     description="Ridimensiona un'immagine mantenendo le proporzioni.",
        #     inputSchema={
        #         "type": "object",
        #         "properties": {
        #             "file":   {"type": "string", "description": "Percorso immagine sorgente"},
        #             "output": {"type": "string", "description": "Percorso immagine output"},
        #             "width":  {"type": "integer", "description": "Larghezza in pixel"},
        #         },
        #         "required": ["file", "output", "width"],
        #     },
        # ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # if name == "resize_image":
    #     ...
    raise ValueError(f"Tool sconosciuto: {name!r}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
