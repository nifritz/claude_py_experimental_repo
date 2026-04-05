#!/usr/bin/env python3
"""
merge_pdfs.py

Merges a list of PDF byte strings into a single PDF.
No Google auth — the caller (N8N, CLI, MCP) handles file I/O.
"""

import io
import logging

import pypdf

log = logging.getLogger(__name__)


def merge(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge a list of PDF byte strings into a single PDF."""
    if not pdf_bytes_list:
        raise ValueError("No PDF files provided")

    writer = pypdf.PdfWriter()
    for i, pdf_bytes in enumerate(pdf_bytes_list):
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) == 0:
            log.warning("File %d has no pages, skipping", i)
            continue
        for page in reader.pages:
            writer.add_page(page)

    if len(writer.pages) == 0:
        raise ValueError("No pages to merge")

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
