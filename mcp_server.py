#!/usr/bin/env python3
"""
mcp_server.py

MCP (Model Context Protocol) server that exposes Python utility scripts
as tools callable by Claude Code.

Transport: stdio (standard MCP transport for subprocess invocation)

Usage:
    python mcp_server.py

Configuration in Claude Code (.mcp.json or settings):
    See README.md → "Integrazione MCP"
"""

import asyncio
import logging
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from scripts.gdrive_folder_to_pdf import run as gdrive_to_pdf_run

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

CREDENTIALS_FILE = os.environ.get("GDRIVE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.environ.get("GDRIVE_TOKEN_FILE", "token.json")

server = Server("python-utils")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="gdrive_folder_to_pdf",
            description=(
                "Converte tutti i file in una cartella Google Drive "
                "(Docs, Sheets, Slides, PDF) in un unico PDF unificato "
                "e lo carica in una cartella Drive di destinazione. "
                "Restituisce il link Google Drive del file caricato."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "src": {
                        "type": "string",
                        "description": "URL o ID della cartella Drive sorgente",
                    },
                    "dst": {
                        "type": "string",
                        "description": "URL o ID della cartella Drive di destinazione",
                    },
                    "output": {
                        "type": "string",
                        "description": "Nome del file PDF di output (default: merged.pdf)",
                    },
                },
                "required": ["src", "dst"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "gdrive_folder_to_pdf":
        result = gdrive_to_pdf_run(
            src_url=arguments["src"],
            dst_url=arguments["dst"],
            output_name=arguments.get("output", "merged.pdf"),
            credentials_file=CREDENTIALS_FILE,
            token_file=TOKEN_FILE,
        )
        return [
            types.TextContent(
                type="text",
                text=f"PDF caricato con successo.\nLink: {result['webViewLink']}\nFile ID: {result['id']}\nNome: {result['name']}",
            )
        ]

    raise ValueError(f"Tool sconosciuto: {name!r}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
