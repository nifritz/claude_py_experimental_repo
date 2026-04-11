#!/usr/bin/env python3
"""
approssima_colori.py — Riduce i colori di un'immagine ai N più vicini dalla palette hardcodata.

Contratto (usato dall'endpoint POST /approssima-colori in api_server.py):
    Input : immagine PIL già aperta in RGB, n_colori: int (default 4)
    Output: immagine PIL con al massimo n_colori colori scelti dalla PALETTE

Logica:
    1. Ogni pixel viene mappato al colore più vicino nella PALETTE (distanza euclidea RGB)
    2. Si contano le frequenze: quali colori della palette compaiono di più
    3. Si selezionano i top-N colori più usati
    4. I pixel che erano stati mappati a colori fuori dal top-N vengono rimappati
       al più vicino tra i top-N
    5. Restituisce l'immagine risultante
"""

import base64
import io
from collections import Counter

from PIL import Image

# ---------------------------------------------------------------------------
# Palette hardcodata — sostituisci questi codici con quelli che preferisci
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


def _nearest(pixel: tuple[int, int, int], candidates: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Restituisce il colore in `candidates` più vicino a `pixel` (distanza euclidea RGB)."""
    r, g, b = pixel
    return min(candidates, key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2)


def approssima(img: Image.Image, n_colori: int = 4) -> Image.Image:
    """
    Riduce l'immagine a massimo `n_colori` colori scelti dalla PALETTE.

    Args:
        img:       Immagine PIL (qualsiasi mode, verrà convertita in RGB)
        n_colori:  Numero massimo di colori da usare (deve essere <= len(PALETTE))

    Returns:
        Immagine PIL in mode RGB con al massimo n_colori colori.
    """
    n_colori = max(1, min(n_colori, len(PALETTE)))

    rgb = img.convert("RGB")
    pixels: list[tuple[int, int, int]] = list(rgb.getdata())  # type: ignore[assignment]

    # Step 1: mappa ogni pixel al colore più vicino nella palette completa
    mapped = [_nearest(p, PALETTE) for p in pixels]

    # Step 2: frequenze → top-N colori più usati
    counts: Counter[tuple[int, int, int]] = Counter(mapped)
    top_n: list[tuple[int, int, int]] = [c for c, _ in counts.most_common(n_colori)]

    # Step 3: remap pixel fuori dal top-N al più vicino tra i top-N
    top_n_set = set(top_n)
    final = [c if c in top_n_set else _nearest(c, top_n) for c in mapped]

    result = Image.new("RGB", rgb.size)
    result.putdata(final)  # type: ignore[arg-type]
    return result


def to_base64_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
