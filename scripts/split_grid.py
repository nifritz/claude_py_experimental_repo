#!/usr/bin/env python3
"""
split_grid.py — Logica per dividere una sprite sheet in celle singole.

Contratto (usato dall'endpoint POST /split-grid in api_server.py):
    Input : immagine PIL già aperta in RGBA, rows: int, cols: int
    Output: lista di dict {"base64": str, "index": int}

Logica di split:
    1. Divide l'immagine in celle di dimensione uguale (width/cols x height/rows)
    2. Per ogni cella fa autocrop del whitespace bianco ai bordi (soglia 240/255)
    3. Aggiunge padding uniforme attorno al soggetto ritagliato
    4. Quadra la cella (sfondo bianco, soggetto centrato)
    5. Restituisce ogni cella come PNG base64
    Index: 0=top-left, incrementa sinistra->destra, riga per riga, ultimo=bottom-right
"""

import base64
import io

from PIL import Image

# Pixel value minimo per considerare un pixel "bianco" (0-255, più alto = più tollerante)
WHITE_THRESHOLD = 240

# Padding da aggiungere attorno al soggetto dopo autocrop (pixel nella cella originale)
CONTENT_PADDING = 15


def autocrop_and_pad(cell: Image.Image) -> Image.Image:
    """
    Trova il bounding box del contenuto non-bianco, aggiunge padding,
    poi crea un'immagine quadrata con sfondo bianco e contenuto centrato.
    Se la cella è tutta bianca la restituisce invariata (come quadrato bianco).
    """
    rgb = cell.convert("RGB")
    w, h = rgb.size

    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False

    pixels = rgb.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if r < WHITE_THRESHOLD or g < WHITE_THRESHOLD or b < WHITE_THRESHOLD:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                found = True

    if not found:
        side = min(w, h)
        return Image.new("RGBA", (side, side), (255, 255, 255, 255))

    left = max(0, min_x - CONTENT_PADDING)
    top = max(0, min_y - CONTENT_PADDING)
    right = min(w, max_x + CONTENT_PADDING + 1)
    bottom = min(h, max_y + CONTENT_PADDING + 1)

    cropped = cell.crop((left, top, right, bottom)).convert("RGBA")

    side = max(cropped.width, cropped.height)
    square = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    ox = (side - cropped.width) // 2
    oy = (side - cropped.height) // 2
    square.paste(cropped, (ox, oy), cropped)

    return square


def to_base64_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def split(img: Image.Image, rows: int, cols: int) -> list[dict]:
    """
    Divide img in rows×cols celle, applica autocrop+pad a ciascuna,
    e restituisce la lista di {"base64": str, "index": int}.
    """
    total_w, total_h = img.size
    cell_w = total_w // cols
    cell_h = total_h // rows

    images = []
    index = 0

    for row in range(rows):
        for col in range(cols):
            left = col * cell_w
            top = row * cell_h
            right = (col + 1) * cell_w if col < cols - 1 else total_w
            bottom = (row + 1) * cell_h if row < rows - 1 else total_h

            cell = img.crop((left, top, right, bottom))
            cell = autocrop_and_pad(cell)

            images.append({"base64": to_base64_png(cell), "index": index})
            index += 1

    return images
