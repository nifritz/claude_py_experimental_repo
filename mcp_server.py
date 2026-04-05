#!/usr/bin/env python3
"""
mcp_server.py

MCP (Model Context Protocol) server that exposes Python utility scripts
as tools callable by Claude Code.

Transport: stdio (standard MCP transport for subprocess invocation)

Usage:
    python mcp_server.py
"""

import asyncio
import logging
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from scripts.merge_pdfs import merge

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

server = Server("python-utils")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="merge_pdfs",
            description=(
                "Unisce più file PDF in un unico PDF. "
                "Accetta una lista di percorsi file all'interno del workspace "
                "e salva il risultato nel percorso indicato."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista di percorsi dei file PDF da unire (in ordine)",
                    },
                    "output": {
                        "type": "string",
                        "description": "Percorso del file PDF di output",
                    },
                },
                "required": ["files", "output"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "merge_pdfs":
        file_paths: list[str] = arguments["files"]
        output_path: str = arguments["output"]

        pdf_bytes_list: list[bytes] = []
        for path in file_paths:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"File non trovato: {path!r}")
            pdf_bytes_list.append(p.read_bytes())

        merged = merge(pdf_bytes_list)
        Path(output_path).write_bytes(merged)

        return [
            types.TextContent(
                type="text",
                text=f"PDF uniti con successo ({len(file_paths)} file).\nSalvato in: {output_path}",
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
