#!/usr/bin/env python3
"""
approssima_colori.py — Riduce i colori di un'immagine ai N più vicini dalla palette hardcodata.

Contratto (usato dall'endpoint POST /approssima-colori in api_server.py):
    Input : immagine PIL già aperta, n_colori: int (default 4)
    Output: immagine PIL RGB con al massimo n_colori colori scelti dalla PALETTE

Logica:
    1. Si costruisce una palette PIL dai 10 colori hardcodati
    2. PIL.quantize(palette=..., dither=0) mappa ogni pixel al colore più vicino
       senza dithering → regioni piatte e pulite, zero artefatti
    3. Si contano le frequenze degli indici palette usati → top-N più frequenti
    4. I pixel mappati a colori fuori dal top-N vengono rimappati al più vicino
       tra i top-N (sempre nearest-neighbor, zero dithering)
    5. Restituisce l'immagine come RGB
"""

import base64
import io
from collections import Counter

from PIL import Image

# ---------------------------------------------------------------------------
# Palette hardcodata — sostituisci questi colori con quelli che preferisci
# ---------------------------------------------------------------------------
PALETTE: list[tuple[int, int, int]] = [
    (245, 245, 245),  # #F5F5F5  bianco caldo
    (26,  26,  26),   # #1A1A1A  nero matte
    (204,  30,  30),  # #CC1E1E  rosso segnale
    (59, 130, 196),   # #3B82C4  blu cielo
    (59, 170,  68),   # #3BAA44  verde erba
    (240, 192,  32),  # #F0C020  giallo girasole
    (224,  96,  16),  # #E06010  arancio zucca
    (102,  51, 187),  # #6633BB  viola
    (204,  34, 136),  # #CC2288  magenta
    (144, 144, 144),  # #909090  grigio argento
]
# ---------------------------------------------------------------------------


def _build_palette_image() -> tuple[Image.Image, list[int]]:
    """Costruisce l'immagine PIL in mode P con i colori della PALETTE."""
    flat: list[int] = []
    for r, g, b in PALETTE:
        flat.extend([r, g, b])
    flat.extend([0, 0, 0] * (256 - len(PALETTE)))
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(flat)
    return palette_img, flat


def approssima(img: Image.Image, n_colori: int = 4) -> Image.Image:
    """
    Riduce l'immagine a massimo `n_colori` colori scelti dalla PALETTE.
    Nessun dithering: le zone di colore sono piatte e pulite.

    Args:
        img:       Immagine PIL (qualsiasi mode)
        n_colori:  Numero massimo di colori da usare (1 ≤ n ≤ len(PALETTE))

    Returns:
        Immagine PIL in mode RGB con al massimo n_colori colori.
    """
    n_colori = max(1, min(n_colori, len(PALETTE)))

    palette_img, flat_palette = _build_palette_image()

    # Step 1: quantizza sull'intera PALETTE senza dithering → zone piatte e pulite
    quantized = img.convert("RGB").quantize(palette=palette_img, dither=0)

    # Step 2: frequenze degli indici → seleziona i top-N più usati
    counts: Counter[int] = Counter(quantized.getdata())
    top_n_indices: set[int] = {
        idx for idx, _ in counts.most_common(n_colori) if idx < len(PALETTE)
    }
    top_n_list = list(top_n_indices)

    # Step 3: costruisci tabella di remap 256 → top-N (nearest-neighbor, no dithering)
    def nearest_in_top_n(idx: int) -> int:
        if idx in top_n_indices:
            return idx
        if idx >= len(PALETTE):
            return top_n_list[0]
        r, g, b = PALETTE[idx]
        return min(
            top_n_list,
            key=lambda i: (PALETTE[i][0] - r) ** 2 + (PALETTE[i][1] - g) ** 2 + (PALETTE[i][2] - b) ** 2,
        )

    remap = [nearest_in_top_n(i) for i in range(256)]

    # Step 4: applica il remap e converti in RGB
    final_pixels = [remap[p] for p in quantized.getdata()]
    result_p = Image.new("P", quantized.size)
    result_p.putpalette(flat_palette)
    result_p.putdata(final_pixels)

    return result_p.convert("RGB")


def to_base64_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
