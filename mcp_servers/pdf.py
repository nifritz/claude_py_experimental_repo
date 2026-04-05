#!/usr/bin/env python3
"""
MCP server — PDF

Tool per la manipolazione di file PDF.
Ogni script in scripts/ che lavora con PDF va esposto qui.

Avvio (gestito da Claude Code tramite .mcp.json):
    python mcp_servers/pdf.py
"""

import asyncio
import logging
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from scripts.merge_pdfs import merge

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

server = Server("pdf")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="merge_pdfs",
            description=(
                "Unisce più file PDF in un unico PDF. "
                "Accetta una lista di percorsi file nel workspace "
                "e salva il risultato nel percorso indicato."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Percorsi dei PDF da unire (in ordine)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Percorso del PDF di output",
                    },
                },
                "required": ["files", "output"],
            },
        ),
        # Aggiungi qui altri tool PDF:
        # - split_pdf
        # - compress_pdf
        # - extract_pages
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "merge_pdfs":
        file_paths: list[str] = arguments["files"]
        output_path: str = arguments["output"]

        pdf_bytes_list = [Path(p).read_bytes() for p in file_paths]
        merged = merge(pdf_bytes_list)
        Path(output_path).write_bytes(merged)

        return [types.TextContent(
            type="text",
            text=f"PDF uniti ({len(file_paths)} file) → {output_path}",
        )]

    raise ValueError(f"Tool sconosciuto: {name!r}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
