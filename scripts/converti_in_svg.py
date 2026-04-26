#!/usr/bin/env python3
"""
converti_in_svg.py — Vettorizzazione AMS-ready di un'immagine in SVG.

Contratto converti() — usato dall'endpoint POST /converti-in-svg:
    Input : bytes di un PNG (immagine binaria)
    Output: stringa contenente l'SVG completo (XML UTF-8) — apre direttamente in Inkscape

    Logica:
        1. Threshold a livello di grigio (THRESHOLD_BLACK=80) per separare le
           regioni "chiare" (>= soglia) dal nero del lineart.
        2. Connected components 8-connettività sulle regioni chiare.
        3. Sfondo = il componente più grande tra quelli che toccano il bordo.
        4. Filtra componenti < MIN_AREA pixel.
        5. Per ogni regione: traccia con potrace e genera un <path> colorato
           con colore HSV distinto.
        6. Lineart nero costruito come differenza (fill-rule="evenodd") tra
           il rettangolo dell'immagine e tutte le regioni + lo sfondo.
        7. PNG originale embeddato in base64 (display:none) per riferimento.
"""

import base64
import colorsys

import cv2
import numpy as np
import potrace

MIN_AREA = 50
THRESHOLD_BLACK = 80
POTRACE_ARGS = dict(turdsize=2, alphamax=1.0, opticurve=True, opttolerance=0.2)


def _mask_to_svg_path(mask: np.ndarray) -> str:
    bmp = potrace.Bitmap(~mask.astype(bool))
    path = bmp.trace(**POTRACE_ARGS)
    parts: list[str] = []
    for curve in path:
        s = curve.start_point
        parts.append(f"M{s.x:.2f},{s.y:.2f}")
        for seg in curve.segments:
            if seg.is_corner:
                parts.append(f"L{seg.c.x:.2f},{seg.c.y:.2f}")
                parts.append(f"L{seg.end_point.x:.2f},{seg.end_point.y:.2f}")
            else:
                parts.append(
                    f"C{seg.c1.x:.2f},{seg.c1.y:.2f} "
                    f"{seg.c2.x:.2f},{seg.c2.y:.2f} "
                    f"{seg.end_point.x:.2f},{seg.end_point.y:.2f}"
                )
        parts.append("Z")
    return " ".join(parts)


def _distinct_color(i: int, total: int) -> str:
    hue = (i / max(total, 1)) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.95)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def converti(img_bytes: bytes) -> str:
    """
    Vettorizza un PNG in un SVG AMS-ready (regioni colorate + lineart nero
    + PNG originale embeddato).

    Restituisce la stringa SVG completa (XML UTF-8). Il file risultante
    si apre direttamente in Inkscape.
    """
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Immagine non decodificabile")
    h, w = img.shape

    region_mask = img >= THRESHOLD_BLACK
    mask_u8 = region_mask.astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_u8, connectivity=8
    )

    border: set[int] = set()
    border.update(np.unique(labels[0, :]).tolist())
    border.update(np.unique(labels[-1, :]).tolist())
    border.update(np.unique(labels[:, 0]).tolist())
    border.update(np.unique(labels[:, -1]).tolist())
    border.discard(0)
    bg_label = (
        max(border, key=lambda lbl: stats[lbl, cv2.CC_STAT_AREA]) if border else None
    )

    regions: list[tuple[int, int]] = []
    for lbl in range(1, num_labels):
        if lbl == bg_label:
            continue
        area = int(stats[lbl, cv2.CC_STAT_AREA])
        if area < MIN_AREA:
            continue
        regions.append((lbl, area))
    regions.sort(key=lambda x: -x[1])

    region_paths: list[tuple[int, int, str]] = []
    for i, (lbl, area) in enumerate(regions):
        d = _mask_to_svg_path(labels == lbl)
        region_paths.append((i, area, d))

    bg_d = ""
    if bg_label is not None:
        bg_d = _mask_to_svg_path(labels == bg_label)

    png_b64 = base64.b64encode(img_bytes).decode("ascii")

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        "  <title>AMS-ready</title>",
        f'  <image id="originale" x="0" y="0" width="{w}" height="{h}" '
        f'xlink:href="data:image/png;base64,{png_b64}" style="display:none"/>',
        '  <g id="regioni">',
    ]
    for i, area, d in region_paths:
        color = _distinct_color(i, len(region_paths))
        out.append(
            f'    <path id="regione-{i + 1}" data-area="{area}" '
            f'fill="{color}" fill-rule="evenodd" stroke="none" d="{d}"/>'
        )
    out.append("  </g>")

    rect_d = f"M0,0 L{w},0 L{w},{h} L0,{h} Z"
    sub_paths = [rect_d]
    if bg_d:
        sub_paths.append(bg_d)
    for _, _, d in region_paths:
        sub_paths.append(d)
    lineart_d = " ".join(sub_paths)

    out.append('  <g id="linee-nere">')
    out.append(
        f'    <path id="lineart" fill="#000000" fill-rule="evenodd" '
        f'stroke="none" d="{lineart_d}"/>'
    )
    out.append("  </g>")
    out.append("</svg>")

    return "\n".join(out)
