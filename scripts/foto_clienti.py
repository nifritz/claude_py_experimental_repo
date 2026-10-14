"""
foto_clienti.py

Logica pura del servizio foto dei clienti (Bimbi Unici): validazione, rate limit,
generazione del codice e salvataggio su disco. Nessun riferimento HTTP: gli
errori sono eccezioni `FotoError` che `api_server.py` traduce in status code.

Il servizio è esposto su internet: i percorsi si costruiscono SOLO da valori
validati (handle del prodotto controllato, codice generato qui, nome ripulito).
Ogni prodotto ha la sua cartella, col nome del suo handle: nessuna lista da tenere.
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_BYTES = 26_214_400  # 25 MB
CHUNK_BYTES = 1024 * 1024
MIN_FREE_BYTES = 10 * 1024**3  # sotto i 10 GB liberi non si salva più

LETTERA_CODICE = "F"

# Formato Pillow -> estensione (si decide dal contenuto, mai dal nome inviato).
FORMATI = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "HEIF": "heic", "WEBP": "webp"}

ALFABETO_CODICE = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # niente 0, O, 1, I, L
LUNGHEZZA_CODICE = 5

RATE_PER_IP_ORA = 10
RATE_TOTALE_GIORNO = 200
PROXY_SUBNET = ipaddress.ip_network("172.18.0.0/16")

FUSO = ZoneInfo("Europe/Rome")
_PRODOTTO_RE = re.compile(
    r"[a-z0-9][a-z0-9-]{0,79}"
)  # handle Shopify: niente punti né barre
_NOME_MAX = 40
_NOME_ORIGINALE_MAX = 255

_lock = threading.Lock()


class FotoError(Exception):
    """Errore di dominio; `kind` viene mappato su uno status HTTP dall'endpoint."""

    kind = "errore"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ProdottoNonValido(FotoError):
    kind = "prodotto"


class FileTroppoGrande(FotoError):
    kind = "dimensione"


class FormatoNonSupportato(FotoError):
    kind = "formato"


class DiscoPieno(FotoError):
    kind = "disco"


class TroppeRichieste(FotoError):
    kind = "rate_limit"


# --------------------------------------------------------------------------- #
# Configurazione
# --------------------------------------------------------------------------- #


def get_foto_dir() -> Path:
    """Radice di salvataggio (letta a ogni chiamata, così i test possono cambiarla)."""
    return Path(os.environ.get("FOTO_DIR", "/app/caricati"))


# --------------------------------------------------------------------------- #
# Rate limit in memoria (uvicorn ha 1 worker)
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Max `per_ip_ora` richieste/ora per IP e `totale_giorno` richieste/giorno.

    Si registrano solo le richieste ammesse: chi viene respinto non allunga la
    propria penalità e la memoria resta limitata (<= totale_giorno timestamp).
    """

    def __init__(
        self, per_ip_ora: int = RATE_PER_IP_ORA, totale_giorno: int = RATE_TOTALE_GIORNO
    ) -> None:
        self.per_ip_ora = per_ip_ora
        self.totale_giorno = totale_giorno
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self._per_ip: dict[str, deque[float]] = {}
        self._totale: deque[float] = deque()

    def consenti(self, ip: str, ora: float | None = None) -> bool:
        ora = time.time() if ora is None else ora
        with self._lock:
            while self._totale and self._totale[0] <= ora - 86400:
                self._totale.popleft()
            for chiave in list(self._per_ip):
                coda = self._per_ip[chiave]
                while coda and coda[0] <= ora - 3600:
                    coda.popleft()
                if not coda:
                    del self._per_ip[chiave]

            if len(self._totale) >= self.totale_giorno:
                return False
            coda_ip = self._per_ip.get(ip)
            if coda_ip is not None and len(coda_ip) >= self.per_ip_ora:
                return False

            self._totale.append(ora)
            self._per_ip.setdefault(ip, deque()).append(ora)
            return True


limiter = RateLimiter()


def ip_cliente(client_host: str | None, x_forwarded_for: str | None) -> str:
    """IP del cliente: X-Forwarded-For (primo valore) solo se la richiesta arriva
    dal reverse proxy (subnet 172.18.0.0/16); altrimenti l'host della connessione."""
    host = client_host or "sconosciuto"
    try:
        dal_proxy = ipaddress.ip_address(host) in PROXY_SUBNET
    except ValueError:
        dal_proxy = False
    if dal_proxy and x_forwarded_for:
        primo = x_forwarded_for.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(primo))
        except ValueError:
            pass  # header malformato: ripiego sull'host della connessione
    return host


# --------------------------------------------------------------------------- #
# Validazione
# --------------------------------------------------------------------------- #


def valida_prodotto(prodotto: str | None) -> str:
    """Handle Shopify ([a-z0-9-], max 80) = nome della cartella, o ProdottoNonValido."""
    if not prodotto or not _PRODOTTO_RE.fullmatch(prodotto):
        raise ProdottoNonValido("Prodotto non valido")
    return prodotto


def pulisci_nome(filename: str | None) -> str:
    """Nome inviato -> senza estensione, solo [A-Za-z0-9-], max 40; 'foto' se vuoto."""
    nome = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." in nome:
        nome = nome.rsplit(".", 1)[0]
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    nome = re.sub(r"[\s_]+", "-", nome)
    nome = re.sub(r"[^A-Za-z0-9-]", "", nome)
    nome = re.sub(r"-{2,}", "-", nome)[:_NOME_MAX].strip("-")
    return nome or "foto"


def controlla_spazio(foto_dir: Path | None = None) -> None:
    """Solleva DiscoPieno se lo spazio libero è sotto MIN_FREE_BYTES."""
    foto_dir = foto_dir or get_foto_dir()
    foto_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(foto_dir).free < MIN_FREE_BYTES:
        raise DiscoPieno("Spazio su disco insufficiente")


def ispeziona_immagine(data: bytes) -> tuple[str, str, int, int]:
    """Verifica il CONTENUTO (non il nome) senza decodificare i pixel.

    Ritorna (formato, estensione, larghezza, altezza) o solleva FormatoNonSupportato.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            formato = img.format or ""
            larghezza, altezza = img.size
    except Exception as exc:  # noqa: BLE001 — qualunque errore = non è un'immagine valida
        raise FormatoNonSupportato("Formato non supportato") from exc
    ext = FORMATI.get(formato)
    if ext is None or larghezza <= 0 or altezza <= 0:
        raise FormatoNonSupportato("Formato non supportato")
    return formato, ext, larghezza, altezza


# --------------------------------------------------------------------------- #
# Codice e salvataggio
# --------------------------------------------------------------------------- #


def _codice_casuale(ora: datetime) -> str:
    suffisso = "".join(secrets.choice(ALFABETO_CODICE) for _ in range(LUNGHEZZA_CODICE))
    return f"{LETTERA_CODICE}-{ora:%m%d}-{suffisso}"


def genera_codice(ora: datetime, cartella_mese: Path) -> str:
    """Codice 'F-<MMGG>-<5 caratteri>', rigenerato se già usato nel mese."""
    while True:
        codice = _codice_casuale(ora)
        if not cartella_mese.is_dir() or not any(cartella_mese.glob(f"*_{codice}_*")):
            return codice


def salva_foto(
    data: bytes,
    filename: str | None,
    prodotto: str | None,
) -> dict:
    """Salva i byte ORIGINALI (nessuna ricodifica), un file solo: data, codice e
    prodotto stanno nel percorso, il nome originale nella riga dell'ordine.

    Ritorna {"codice", "nome", "byte"}. Solleva FotoError per input non validi.
    """
    cartella = valida_prodotto(prodotto)
    _formato, ext, _larghezza, _altezza = ispeziona_immagine(data)
    controlla_spazio()

    ora = datetime.now(FUSO)
    cartella_mese = get_foto_dir() / cartella / f"{ora:%Y-%m}"
    nome_originale = (filename or "")[:_NOME_ORIGINALE_MAX]
    nome_pulito = pulisci_nome(filename)

    with _lock:
        cartella_mese.mkdir(parents=True, exist_ok=True)
        codice = genera_codice(ora, cartella_mese)
        percorso_foto = (
            cartella_mese / f"{ora:%Y%m%d-%H%M}_{codice}_{nome_pulito}.{ext}"
        )
        with open(percorso_foto, "xb") as f:  # "x": mai sovrascrivere
            try:
                f.write(data)
            except Exception:
                f.close()
                percorso_foto.unlink(missing_ok=True)  # solo quello creato qui
                raise

    return {"codice": codice, "nome": nome_originale, "byte": len(data)}
