#!/usr/bin/env python3
"""
split_grid.py — Logica per dividere una sprite sheet in celle singole.

Contratto (usato dall'endpoint POST /split-grid in api_server.py):
    Input : immagine PIL già aperta in RGBA, rows: int, cols: int
    Output: lista di dict {"base64": str, "index": int}

Logica di split:
    1. Divide l'immagine in celle di dimensione uguale (width/cols x height/rows)
    2. Trova il componente connesso più grande (= soggetto)
    3. BFS dal bordo: pixel non-bianchi raggiungibili senza attraversare il soggetto = sporcizia esterna
    4. Blank delle sole sporcizie esterne; contenuto interno al soggetto (buchi, dettagli) intatto
    5. Bounding box del soggetto + padding, quadratura e centramento
    6. Restituisce ogni cella come PNG base64
    Index: 0=top-left, incrementa sinistra->destra, riga per riga, ultimo=bottom-right
"""

import base64
import io

from PIL import Image

# Pixel value minimo per considerare un pixel "bianco" (0-255, più alto = più tollerante)
WHITE_THRESHOLD = 240

# Padding da aggiungere attorno al soggetto dopo autocrop (pixel nella cella originale)
CONTENT_PADDING = 15


def _largest_connected_component(rgb: Image.Image) -> set[tuple[int, int]]:
    """
    Restituisce l'insieme di coordinate (x, y) del componente connesso più grande
    tra i pixel non-bianchi. Connettività 4 (N/S/E/W).
    Restituisce un insieme vuoto se la cella è tutta bianca.
    """
    w, h = rgb.size
    pixels = rgb.load()

    dark: set[tuple[int, int]] = set()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if r < WHITE_THRESHOLD or g < WHITE_THRESHOLD or b < WHITE_THRESHOLD:
                dark.add((x, y))

    if not dark:
        return set()

    visited: set[tuple[int, int]] = set()
    largest: set[tuple[int, int]] = set()

    for start in dark:
        if start in visited:
            continue
        component: set[tuple[int, int]] = set()
        queue = [start]
        visited.add(start)
        while queue:
            x, y = queue.pop()
            component.add((x, y))
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (nx, ny) in dark and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
        if len(component) > len(largest):
            largest = component

    return largest


def _external_noise(
    subject: set[tuple[int, int]],
    rgb: Image.Image,
) -> set[tuple[int, int]]:
    """
    BFS dal bordo della cella attraverso tutti i pixel NON appartenenti al soggetto.
    Restituisce i pixel non-bianchi raggiungibili: sono sporcizie esterne al soggetto.
    I pixel non-bianchi NON raggiungibili (interni al soggetto) vengono ignorati e conservati.
    """
    w, h = rgb.size
    pixels = rgb.load()

    visited: set[tuple[int, int]] = set()
    queue: list[tuple[int, int]] = []

    # Parti da tutti i pixel sul bordo della cella che non sono soggetto
    for x in range(w):
        for y in (0, h - 1):
            if (x, y) not in subject and (x, y) not in visited:
                visited.add((x, y))
                queue.append((x, y))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if (x, y) not in subject and (x, y) not in visited:
                visited.add((x, y))
                queue.append((x, y))

    noise: set[tuple[int, int]] = set()

    while queue:
        x, y = queue.pop()
        r, g, b = pixels[x, y]
        if r < WHITE_THRESHOLD or g < WHITE_THRESHOLD or b < WHITE_THRESHOLD:
            noise.add((x, y))
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if (
                0 <= nx < w
                and 0 <= ny < h
                and (nx, ny) not in subject
                and (nx, ny) not in visited
            ):
                visited.add((nx, ny))
                queue.append((nx, ny))

    return noise


def autocrop_and_pad(cell: Image.Image) -> Image.Image:
    """
    Isola il soggetto principale e rimuove le sole sporcizie esterne ad esso.
    I dettagli interni (buchi, scritte, aree scure racchiuse dal soggetto) vengono conservati.
    Crea un'immagine quadrata con sfondo bianco e soggetto centrato.
    Se la cella è tutta bianca la restituisce invariata (come quadrato bianco).
    """
    rgb = cell.convert("RGB")
    w, h = rgb.size

    subject = _largest_connected_component(rgb)

    if not subject:
        side = min(w, h)
        return Image.new("RGBA", (side, side), (255, 255, 255, 255))

    noise = _external_noise(subject, rgb)

    min_x = min(x for x, _ in subject)
    max_x = max(x for x, _ in subject)
    min_y = min(y for _, y in subject)
    max_y = max(y for _, y in subject)

    cell_rgba = cell.convert("RGBA")
    out_pix = cell_rgba.load()
    for x, y in noise:
        out_pix[x, y] = (255, 255, 255, 255)

    left = max(0, min_x - CONTENT_PADDING)
    top = max(0, min_y - CONTENT_PADDING)
    right = min(w, max_x + CONTENT_PADDING + 1)
    bottom = min(h, max_y + CONTENT_PADDING + 1)

    cropped = cell_rgba.crop((left, top, right, bottom))

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
