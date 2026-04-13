# reduce-image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere `scripts/reduce_image.py` e l'endpoint `POST /reduce-image` che riduce il peso di un'immagine PNG sotto una soglia in MB, scalando le dimensioni se necessario.

**Architecture:** Lo script puro `reduce_image.py` implementa la logica di riduzione (stima matematica del fattore di scala + fallback a step del 10%); l'endpoint in `api_server.py` scarica l'immagine via URL, chiama `reduce()`, e restituisce il risultato in base64 PNG. Se l'immagine è già sotto soglia viene restituita invariata.

**Tech Stack:** Python 3, Pillow (`Image`, `Image.LANCZOS`), FastAPI, Pydantic, pytest

---

### Task 1: Script `scripts/reduce_image.py` — TDD

**Files:**
- Create: `scripts/reduce_image.py`
- Create: `tests/test_reduce_image.py`

- [ ] **Step 1: Crea il file di test `tests/test_reduce_image.py`**

```python
import io
import math

import pytest
from PIL import Image

from scripts.reduce_image import reduce, _png_bytes


def _make_image(width: int, height: int, color=(255, 0, 0)) -> Image.Image:
    """Crea un'immagine RGB di test del colore specificato."""
    img = Image.new("RGB", (width, height), color)
    return img


def _size_mb(img: Image.Image) -> float:
    return len(_png_bytes(img)) / (1024 * 1024)


class TestPngBytes:
    def test_returns_bytes(self):
        img = _make_image(100, 100)
        result = _png_bytes(img)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_valid_png_header(self):
        img = _make_image(100, 100)
        result = _png_bytes(img)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"


class TestReduceAlreadyUnderThreshold:
    def test_small_image_returned_unchanged(self):
        # Immagine 10x10 pesa sicuramente meno di 1 MB
        img = _make_image(10, 10)
        result = reduce(img, max_mb=1)
        assert result is img  # stesso oggetto, non ricopiata

    def test_dimensions_unchanged_when_under_threshold(self):
        img = _make_image(50, 50)
        result = reduce(img, max_mb=10)
        assert result.width == 50
        assert result.height == 50


class TestReduceScalesDown:
    def test_result_under_threshold(self):
        # Immagine 4000x4000 solid color: PNG comprime bene ma pesiamo comunque
        # Usiamo rumore per forzare un PNG grande
        import random
        pixels = [random.randint(0, 255) for _ in range(800 * 800 * 3)]
        img = Image.frombytes("RGB", (800, 800), bytes(pixels))
        original_size = len(_png_bytes(img))
        # Scegliamo una soglia sotto il peso attuale
        max_bytes = original_size // 4
        max_mb = max(1, max_bytes // (1024 * 1024))
        if max_mb == 0:
            max_mb = 1
        # Se l'immagine rumorosa pesa già meno di 1 MB, skippiamo il test
        if _size_mb(img) <= max_mb:
            pytest.skip("Immagine di test già sotto la soglia minima testabile")
        result = reduce(img, max_mb=max_mb)
        assert len(_png_bytes(result)) <= max_mb * 1024 * 1024

    def test_result_is_smaller_than_original(self):
        import random
        pixels = [random.randint(0, 255) for _ in range(1000 * 1000 * 3)]
        img = Image.frombytes("RGB", (1000, 1000), bytes(pixels))
        original_bytes = len(_png_bytes(img))
        # Soglia = metà del peso originale, in MB (minimo 1)
        half_mb = max(1, (original_bytes // 2) // (1024 * 1024))
        if _size_mb(img) <= half_mb:
            pytest.skip("Immagine di test già sotto la soglia minima testabile")
        result = reduce(img, max_mb=half_mb)
        assert result.width < img.width
        assert result.height < img.height

    def test_aspect_ratio_preserved(self):
        import random
        pixels = [random.randint(0, 255) for _ in range(800 * 400 * 3)]
        img = Image.frombytes("RGB", (800, 400), bytes(pixels))
        if _size_mb(img) <= 1:
            pytest.skip("Immagine di test già sotto la soglia minima testabile")
        result = reduce(img, max_mb=1)
        original_ratio = img.width / img.height
        result_ratio = result.width / result.height
        assert abs(original_ratio - result_ratio) < 0.01
```

- [ ] **Step 2: Verifica che i test falliscano (modulo non esiste)**

```bash
pytest tests/test_reduce_image.py -v
```

Atteso: errore `ModuleNotFoundError` o `ImportError` — `scripts/reduce_image.py` non esiste ancora.

- [ ] **Step 3: Crea `scripts/reduce_image.py`**

```python
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
```

- [ ] **Step 4: Esegui i test**

```bash
pytest tests/test_reduce_image.py -v
```

Atteso: tutti i test PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reduce_image.py tests/test_reduce_image.py
git commit -m "feat(reduce-image): add reduce_image script with tests"
```

---

### Task 2: Endpoint `POST /reduce-image` in `api_server.py`

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_reduce_image.py` (aggiunta test endpoint)

- [ ] **Step 1: Aggiungi test dell'endpoint a `tests/test_reduce_image.py`**

Aggiungi in fondo al file esistente:

```python
# ---------------------------------------------------------------------------
# Test endpoint /reduce-image
# ---------------------------------------------------------------------------
import base64
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)


def _make_png_bytes(width: int, height: int) -> bytes:
    import random
    pixels = [random.randint(0, 255) for _ in range(width * height * 3)]
    img = Image.frombytes("RGB", (width, height), bytes(pixels))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestReduceImageEndpoint:
    def test_returns_base64_key(self):
        png_data = _make_png_bytes(10, 10)
        mock_resp = MagicMock()
        mock_resp.content = png_data
        mock_resp.raise_for_status = MagicMock()

        with patch("api_server.http_requests.get", return_value=mock_resp):
            resp = client.post(
                "/reduce-image",
                json={"image_url": "http://fake/img.png", "max_mb": 5},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "base64" in body
        decoded = base64.b64decode(body["base64"])
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_invalid_max_mb_returns_400(self):
        resp = client.post(
            "/reduce-image",
            json={"image_url": "http://fake/img.png", "max_mb": 0},
        )
        assert resp.status_code == 400

    def test_download_error_returns_400(self):
        import requests as req_lib
        with patch(
            "api_server.http_requests.get",
            side_effect=req_lib.RequestException("timeout"),
        ):
            resp = client.post(
                "/reduce-image",
                json={"image_url": "http://fake/img.png", "max_mb": 5},
            )
        assert resp.status_code == 400

    def test_invalid_image_returns_400(self):
        mock_resp = MagicMock()
        mock_resp.content = b"not an image"
        mock_resp.raise_for_status = MagicMock()

        with patch("api_server.http_requests.get", return_value=mock_resp):
            resp = client.post(
                "/reduce-image",
                json={"image_url": "http://fake/img.png", "max_mb": 5},
            )
        assert resp.status_code == 400
```

- [ ] **Step 2: Esegui i test endpoint per verificare che falliscano**

```bash
pytest tests/test_reduce_image.py::TestReduceImageEndpoint -v
```

Atteso: FAIL — endpoint non esiste ancora (404 o ImportError).

- [ ] **Step 3: Modifica `api_server.py` — aggiungi import, modello e endpoint**

Aggiungi l'import in cima agli altri import da `scripts`:

```python
from scripts.reduce_image import reduce as reduce_image
from scripts.reduce_image import to_base64_png as reduce_to_base64
```

Aggiungi il modello Pydantic dopo `ApprossimaColoriRequest`:

```python
class ReduceImageRequest(BaseModel):
    image_url: str
    max_mb: int
```

Aggiungi l'endpoint dopo `/approssima-colori`:

```python
@app.post("/reduce-image")
def reduce_image_endpoint(req: ReduceImageRequest) -> dict:
    """
    Riduce il peso di un'immagine PNG sotto la soglia specificata in MB.

    Body JSON: {"image_url": "https://...", "max_mb": 5}
    Response : {"base64": "<png base64>"}

    Se l'immagine è già sotto la soglia viene restituita invariata.
    Strategia: compressione PNG massima, poi scala le dimensioni se necessario.
    """
    if req.max_mb < 1:
        raise HTTPException(status_code=400, detail="max_mb deve essere >= 1")

    try:
        resp = http_requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except http_requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Errore download immagine: {e}") from e

    try:
        img = Image.open(io.BytesIO(resp.content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Immagine non valida: {e}") from e

    original_bytes = len(resp.content)
    result = reduce_image(img, req.max_mb)
    result_bytes = len(reduce_to_base64(result).encode()) * 3 // 4  # stima da base64
    logging.info(
        "reduce-image: max=%d MB, prima=%d bytes, dopo≈%d bytes",
        req.max_mb,
        original_bytes,
        result_bytes,
    )
    return {"base64": reduce_to_base64(result)}
```

Aggiorna anche il docstring dell'app in cima al file aggiungendo la nuova voce agli endpoint:

```python
    POST /reduce-image         → riduce il peso di un'immagine PNG sotto una soglia in MB
```

- [ ] **Step 4: Esegui tutti i test**

```bash
pytest tests/test_reduce_image.py -v
```

Atteso: tutti PASS.

- [ ] **Step 5: Commit**

```bash
git add api_server.py tests/test_reduce_image.py
git commit -m "feat(reduce-image): add POST /reduce-image endpoint"
```

---

### Task 3: Branch push e PR

- [ ] **Step 1: Crea branch e pusha**

```bash
git checkout -b claude/reduce-image-<ID>
git push -u origin claude/reduce-image-<ID>
```

Sostituisci `<ID>` con l'issue number se disponibile, altrimenti un numero incrementale (es. `18`).

- [ ] **Step 2: Verifica suite completa**

```bash
pytest -v
```

Atteso: tutti i test PASS, nessun errore.
