#!/usr/bin/env python3
"""
reduce_image.py — Riduce il peso di un'immagine PNG sotto una soglia in MB.

Contratto reduce() — usato dall'endpoint POST /reduce-image:
    Input : immagine PIL già aperta, max_mb: int (soglia massima in megabyte)
    Output: immagine PIL ridimensionata (o la stessa se già sotto soglia)

    Logica:
        1. Encode PNG compression=9 in memoria; se ≤ soglia, restituisce l'originale
        2. Stima scale = sqrt(target_bytes / current_bytes), clamp [0.05, 0.95]
        3. Ridimensiona e verifica; se ancora sopra soglia applica scale *= 0.9
           per max 5 iterazioni (sempre dall'immagine originale)
        4. Restituisce la migliore immagine ottenuta
"""

import base64
import io
import math

from PIL import Image


def _png_bytes(img: Image.Image) -> bytes:
    """Encode l'immagine come PNG con compressione massima e restituisce i byte."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=9)
    return buf.getvalue()


def to_base64_png(img: Image.Image) -> str:
    """Restituisce l'immagine come stringa base64 PNG."""
    return base64.b64encode(_png_bytes(img)).decode("utf-8")


def reduce(img: Image.Image, max_mb: int) -> Image.Image:
    """
    Riduce il peso dell'immagine sotto max_mb megabyte scalando le dimensioni.
    Se già sotto soglia restituisce lo stesso oggetto img invariato.
    """
    target_bytes = max_mb * 1024 * 1024
    current_bytes = len(_png_bytes(img))

    if current_bytes <= target_bytes:
        return img

    # Stima iniziale del fattore di scala
    scale = math.sqrt(target_bytes / current_bytes)
    scale = max(0.05, min(0.95, scale))

    best: Image.Image = img
    best_size = current_bytes

    for _ in range(6):  # 1 tentativo stimato + 5 fallback
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        candidate = img.resize((new_w, new_h), Image.LANCZOS)
        candidate_bytes = len(_png_bytes(candidate))

        if candidate_bytes < best_size:
            best = candidate
            best_size = candidate_bytes

        if candidate_bytes <= target_bytes:
            return candidate

        scale *= 0.9
        scale = max(0.05, scale)

    return best
