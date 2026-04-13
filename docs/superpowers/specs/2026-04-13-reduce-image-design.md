# Design: reduce_image — endpoint POST /reduce-image

**Date:** 2026-04-13

## Overview

Aggiunge uno script `scripts/reduce_image.py` e l'endpoint `POST /reduce-image` ad `api_server.py`.
Lo scopo è ridurre il peso di un'immagine PNG sotto una soglia in megabyte specificata dal chiamante.
Se l'immagine è già sotto soglia, viene restituita invariata.

## Script `scripts/reduce_image.py`

### Interfaccia pubblica

```python
def reduce(img: Image.Image, max_mb: int) -> Image.Image:
    ...
```

- **Input:** immagine PIL già aperta, soglia massima in MB (intero ≥ 1)
- **Output:** immagine PIL (stessa se già sotto soglia, ridimensionata altrimenti)
- **Formato output:** PNG (lossless), compressione massima (level 9)

### Logica

1. Encode l'immagine in memoria come PNG con `compress_level=9` via helper `_png_bytes(img)`
2. Se `len(encoded) <= max_mb * 1024 * 1024` → restituisce `img` invariata
3. Calcola `target_bytes = max_mb * 1024 * 1024`
4. Stima il fattore di scala: `scale = sqrt(target_bytes / len(encoded))`, clampato a `[0.05, 0.95]`
5. Ridimensiona: `new_w = int(img.width * scale)`, `new_h = int(img.height * scale)`, usando `Image.LANCZOS`
6. Verifica il peso del risultato con `_png_bytes`
7. Se ancora sopra soglia: applica `scale *= 0.9` e ridimensiona dall'immagine originale; ripete max 5 volte
8. Restituisce l'immagine ridimensionata

### Helper interno

```python
def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=9)
    return buf.getvalue()
```

### Note

- Il resize usa sempre l'immagine originale come sorgente (non ridimensiona il già-ridimensionato) per evitare degrado cumulativo
- Il clamp inferiore a 0.05 previene immagini di 1×1 pixel su soglie irraggiungibili
- In caso estremo (5 fallback esauriti), restituisce la miglior immagine ottenuta (la più piccola prodotta)

## Endpoint `POST /reduce-image` in `api_server.py`

### Request body

```json
{"image_url": "https://...", "max_mb": 5}
```

Modello Pydantic:

```python
class ReduceImageRequest(BaseModel):
    image_url: str
    max_mb: int
```

### Validazione

- `max_mb < 1` → HTTP 400

### Logica endpoint

1. Download immagine via `requests.get(req.image_url, timeout=30)`
2. Apertura con `Image.open(...)`  — modalità preservata (no forzatura RGBA)
3. Chiamata a `reduce(img, req.max_mb)`
4. Encode risultato in base64 PNG tramite helper `to_base64_png` (da definire nello script, stesso pattern di `split_grid.py`)
5. Log: `"reduce-image: %d MB max, %d → %d bytes"` (prima e dopo)

### Response

```json
{"base64": "<png base64>"}
```

Stesso formato di `/approssima-colori`.

## Dipendenze

Nessuna nuova dipendenza: `Pillow` è già presente in `pyproject.toml`.

## File modificati / creati

| File | Operazione |
|------|-----------|
| `scripts/reduce_image.py` | Nuovo file |
| `api_server.py` | Aggiunta import + modello + endpoint |
