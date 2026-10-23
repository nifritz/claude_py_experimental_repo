"""
foto_clienti.py

Logica pura del servizio foto dei clienti (Bimbi Unici): validazione, rate limit,
generazione del codice, chiave di sessione, salvataggio e cancellazione su disco.
Nessun riferimento HTTP: gli errori sono eccezioni `FotoError` che `api_server.py`
traduce in status code.

Layout: FOTO_DIR/<handle>/<AAAA-MM>/<CODICE>/<n>_<nome-pulito>.<ext>
Un CODICE ("padre") per carrello = una cartella con al massimo MAX_FOTO foto,
numerate da 1 senza mai rinumerare (n = massimo presente + 1). Il cliente aggiunge
e cancella le proprie foto presentando CODICE + chiave, dove la chiave è un HMAC
del codice col segreto FOTO_SEGRETO: nessuno stato lato server oltre ai file.
I vecchi file piatti (<AAAA-MM>/<AAAAMMGG-HHMM>_<CODICE>_<nome>.<ext>) restano dove
sono e il loro codice non viene mai riassegnato.
Ogni caricamento porta l'email del cliente (obbligatoria): nella cartella del codice
il server tiene `contatto.txt` (email, codice, prodotto, aggiornato). Non è una foto:
non conta nel limite, non entra nella numerazione e la cancellazione (che accetta solo
numeri) non lo raggiunge mai.

Il servizio è esposto su internet: i percorsi si costruiscono SOLO da valori
validati (handle del prodotto controllato, codice con regex chiusa, numero intero,
nome ripulito) e ogni percorso toccato deve risolversi dentro FOTO_DIR.
Ogni prodotto ha la sua cartella, col nome del suo handle: nessuna lista da tenere.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import logging
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

import requests
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
_CODICE_RE = re.compile(rf"F-\d{{4}}-[{ALFABETO_CODICE}]{{{LUNGHEZZA_CODICE}}}")

MAX_FOTO = 6  # foto per cartella (per carrello)
NUMERO_MAX = 99  # oltre non si salva: ogni foto deve restare cancellabile
_NUMERATO_RE = re.compile(r"(\d+)_")
_MESE_RE = re.compile(r"\d{4}-\d{2}")

CONTATTO = "contatto.txt"
_CONTATTO_TMP = ".contatto.txt.tmp"  # non inizia con "<n>_": mai scambiato per una foto
EMAIL_MAX = 254
EMAIL_LOCALE_MAX = 64
# Vietati in ogni parte: spazi e a capo (\s), @ e caratteri di controllo (C0, DEL, C1).
_EMAIL_VIETATI = r"\s@\x00-\x1f\x7f-\x9f"
# parte locale 1..64 @ dominio: etichette non vuote separate da punti, almeno un punto
_EMAIL_RE = re.compile(
    rf"([^{_EMAIL_VIETATI}]{{1,{EMAIL_LOCALE_MAX}}})"
    rf"@([^{_EMAIL_VIETATI}.]+(?:\.[^{_EMAIL_VIETATI}.]+)+)"
)

SEGRETO_MIN = 32
LUNGHEZZA_CHIAVE = 32

RATE_PER_IP_ORA = 20
RATE_TOTALE_GIORNO = 200
RATE_ELIMINA_PER_IP_ORA = 30
RATE_ELIMINA_TOTALE_GIORNO = 500
PROXY_SUBNET = ipaddress.ip_network("172.18.0.0/16")

FUSO = ZoneInfo("Europe/Rome")
_PRODOTTO_RE = re.compile(
    r"[a-z0-9][a-z0-9-]{0,79}"
)  # handle Shopify: niente punti né barre
_NOME_MAX = 40
_NOME_ORIGINALE_MAX = 255

# Notifica a n8n all'apertura di un codice: un extra, mai un requisito del caricamento.
N8N_TIMEOUT_S = 3
_N8N_URL_ENV = "N8N_FOTO_WEBHOOK_URL"
_N8N_SEGRETO_ENV = "N8N_FOTO_SEGRETO"  # diverso da FOTO_SEGRETO (HMAC delle sessioni)

log = logging.getLogger(__name__)

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


class SessioneNonValida(FotoError):
    kind = "sessione"


class NumeroNonValido(FotoError):
    kind = "numero"


class ChiaveNonValida(FotoError):
    kind = "chiave"


class EmailNonValida(FotoError):
    kind = "email"


class ServizioNonConfigurato(FotoError):
    kind = "configurazione"


class TroppeFoto(FotoError):
    kind = "troppe_foto"


class FotoNonTrovata(FotoError):
    kind = "non_trovata"


# --------------------------------------------------------------------------- #
# Configurazione
# --------------------------------------------------------------------------- #


def get_foto_dir() -> Path:
    """Radice di salvataggio (letta a ogni chiamata, così i test possono cambiarla)."""
    return Path(os.environ.get("FOTO_DIR", "/app/caricati"))


def get_segreto() -> bytes | None:
    """FOTO_SEGRETO (letto a ogni chiamata); None se assente o sotto SEGRETO_MIN."""
    segreto = os.environ.get("FOTO_SEGRETO", "")
    if len(segreto) < SEGRETO_MIN:
        return None
    return segreto.encode()


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


limiter = RateLimiter()  # caricamenti
limiter_elimina = RateLimiter(RATE_ELIMINA_PER_IP_ORA, RATE_ELIMINA_TOTALE_GIORNO)


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


def valida_email(email: str | None) -> str:
    """Email normalizzata (strip, dominio minuscolo) o EmailNonValida.

    Controllo solo di forma, senza DNS: max 254 caratteri, una sola @, parte locale
    1..64, dominio con almeno un punto e senza etichette vuote, niente spazi né
    caratteri di controllo. La parte locale resta com'è (per standard è case-sensitive).
    """
    pulita = (email or "").strip()
    if len(pulita) > EMAIL_MAX:
        raise EmailNonValida("Email non valida")
    trovata = _EMAIL_RE.fullmatch(pulita)
    if trovata is None:
        raise EmailNonValida("Email non valida")
    return f"{trovata.group(1)}@{trovata.group(2).lower()}"


def valida_codice(codice: str | None) -> str:
    """Codice 'F-<MMGG>-<5 caratteri>' (regex chiusa) o SessioneNonValida."""
    if not codice or not _CODICE_RE.fullmatch(codice):
        raise SessioneNonValida("Sessione non valida")
    return codice


def chiave_sessione(codice: str) -> str | None:
    """HMAC-SHA256(FOTO_SEGRETO, codice), 32 caratteri hex; None senza segreto."""
    segreto = get_segreto()
    if segreto is None:
        return None
    digest = hmac.new(segreto, codice.encode(), hashlib.sha256).hexdigest()
    return digest[:LUNGHEZZA_CHIAVE]


def verifica_sessione(codice: str | None, chiave: str | None) -> str:
    """Formato del codice (400) -> segreto configurato (503) -> chiave (403)."""
    codice = valida_codice(codice)
    attesa = chiave_sessione(codice)
    if attesa is None:
        raise ServizioNonConfigurato("Servizio non configurato")
    # bytes: compare_digest su str non ASCII solleverebbe TypeError (-> 500)
    if not hmac.compare_digest((chiave or "").encode(), attesa.encode()):
        raise ChiaveNonValida("Chiave non valida")
    return codice


def valida_numero(numero: int) -> int:
    """Numero della foto, intero 1..NUMERO_MAX, o NumeroNonValido."""
    if type(numero) is not int or not 1 <= numero <= NUMERO_MAX:
        raise NumeroNonValido("Numero non valido")
    return numero


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


def _codice_usato(codice: str, radice: Path) -> bool:
    """Usato se esiste, sotto QUALUNQUE prodotto e mese, la cartella <CODICE> o un
    vecchio file piatto *_<CODICE>_*: la chiave dipende solo dal codice, quindi un
    codice riassegnato darebbe accesso alle foto di un altro cliente."""
    return any(radice.glob(f"*/*/{codice}")) or any(radice.glob(f"*/*/*_{codice}_*"))


def genera_codice(ora: datetime, radice: Path) -> str:
    """Codice 'F-<MMGG>-<5 caratteri>', rigenerato se già usato sotto `radice`."""
    while True:
        codice = _codice_casuale(ora)
        if not _codice_usato(codice, radice):
            return codice


def _dentro(percorso: Path, radice: Path) -> bool:
    """True se `percorso`, risolto (symlink compresi), sta dentro `radice`."""
    return percorso.resolve().is_relative_to(radice.resolve())


def trova_cartella(radice: Path, prodotto: str, codice: str) -> Path | None:
    """Cartella della sessione fra i mesi <AAAA-MM> del prodotto, o None.

    Si cerca solo sotto il prodotto richiesto: mai nella cartella di un altro handle.
    """
    base = radice / prodotto
    if not base.is_dir():
        return None
    for mese in sorted(base.iterdir()):
        if not _MESE_RE.fullmatch(mese.name):
            continue
        cartella = mese / codice
        if cartella.is_dir() and _dentro(cartella, radice):
            return cartella
    return None


def _prossimo_numero(cartella: Path) -> int:
    """Massimo presente + 1 (1 se vuota); TroppeFoto oltre MAX_FOTO o NUMERO_MAX.

    Contano solo i file "<n>_*": contatto.txt non è una foto e viene ignorato.
    """
    numeri = [
        int(m.group(1))
        for p in cartella.iterdir()
        if (m := _NUMERATO_RE.match(p.name)) and p.is_file()
    ]
    if len(numeri) >= MAX_FOTO:
        raise TroppeFoto(f"Massimo {MAX_FOTO} foto")
    numero = max(numeri, default=0) + 1
    if numero > NUMERO_MAX:
        raise TroppeFoto("Troppe foto per questa sessione")
    return numero


def _scrivi_contatto(cartella: Path, email: str, codice: str, handle: str) -> None:
    """Scrive contatto.txt se manca o se la mail è cambiata (vale l'ultima); se la
    mail è la stessa non lo tocca (resta il momento di apertura). Atomico: file
    temporaneo nella stessa cartella + rename. Da chiamare sotto `_lock`."""
    percorso = cartella / CONTATTO
    try:
        prima_riga = percorso.read_text(encoding="utf-8").split("\n", 1)[0]
        if prima_riga == f"email: {email}":
            return
    except (OSError, UnicodeDecodeError):
        pass  # assente o illeggibile: si (ri)scrive
    ora = datetime.now(FUSO).isoformat(timespec="seconds")
    testo = f"email: {email}\ncodice: {codice}\nprodotto: {handle}\naggiornato: {ora}\n"
    temporaneo = cartella / _CONTATTO_TMP
    try:
        with open(temporaneo, "w", encoding="utf-8", newline="\n") as f:
            f.write(testo)
        os.replace(temporaneo, percorso)
    except BaseException:
        temporaneo.unlink(missing_ok=True)
        raise


def salva_foto(
    data: bytes,
    filename: str | None,
    prodotto: str | None,
    sessione: str | None = None,
    chiave: str | None = None,
    email: str | None = None,
) -> dict:
    """Come `salva_foto_aprendo`, ma ritorna solo la risposta."""
    return salva_foto_aprendo(data, filename, prodotto, sessione, chiave, email)[0]


def salva_foto_aprendo(
    data: bytes,
    filename: str | None,
    prodotto: str | None,
    sessione: str | None = None,
    chiave: str | None = None,
    email: str | None = None,
) -> tuple[dict, bool]:
    """Salva i byte ORIGINALI (nessuna ricodifica), un file solo per foto: prodotto,
    mese, codice e numero stanno nel percorso, il nome originale nella risposta.

    Senza `sessione` apre un codice nuovo (foto n. 1). Con `sessione` + `chiave`
    aggiunge alla cartella della sessione sotto questo prodotto (anche se di un mese
    precedente) o, se non c'è, la crea nel mese corrente.

    `email` è obbligatoria su ogni caricamento (EmailNonValida, prima di toccare il
    disco): finisce in contatto.txt nella cartella del codice.

    Ritorna (risposta, aperto): la risposta è {"codice", "numero", "chiave", "nome",
    "byte"} ("chiave" è None se FOTO_SEGRETO manca); `aperto` è True solo se questo
    caricamento ha creato la cartella del codice (e quindi contatto.txt).
    Solleva FotoError per input non validi.
    """
    handle = valida_prodotto(prodotto)
    email = valida_email(email)
    if sessione:
        sessione = verifica_sessione(sessione, chiave)
    _formato, ext, _larghezza, _altezza = ispeziona_immagine(data)
    controlla_spazio()

    radice = get_foto_dir()
    ora = datetime.now(FUSO)
    cartella_mese = radice / handle / f"{ora:%Y-%m}"
    nome_originale = (filename or "")[:_NOME_ORIGINALE_MAX]
    nome_pulito = pulisci_nome(filename)

    with _lock:
        if sessione:
            codice = sessione
            cartella = trova_cartella(radice, handle, codice) or cartella_mese / codice
        else:
            codice = genera_codice(ora, radice)
            cartella = cartella_mese / codice
        if not _dentro(cartella, radice):
            raise SessioneNonValida("Sessione non valida")
        aperto = not cartella.exists()
        cartella.mkdir(parents=True, exist_ok=True)
        numero = _prossimo_numero(cartella)
        percorso_foto = cartella / f"{numero}_{nome_pulito}.{ext}"
        with open(percorso_foto, "xb") as f:  # "x": mai sovrascrivere
            try:
                f.write(data)
            except Exception:
                f.close()
                percorso_foto.unlink(missing_ok=True)  # solo quello creato qui
                raise
        try:
            _scrivi_contatto(cartella, email, codice, handle)
        except Exception:
            percorso_foto.unlink(missing_ok=True)  # niente foto senza contatto
            raise

    risposta = {
        "codice": codice,
        "numero": numero,
        "chiave": chiave_sessione(codice),
        "nome": nome_originale,
        "byte": len(data),
    }
    return risposta, aperto


def notifica_apertura(codice: str, prodotto: str) -> None:
    """Avvisa n8n che si è aperto un codice nuovo. Da eseguire DOPO la risposta
    (BackgroundTasks): non solleva mai e non ritenta.

    Senza N8N_FOTO_WEBHOOK_URL e N8N_FOTO_SEGRETO non fa nulla. Il body ha solo
    codice, prodotto e ora: niente email, nomi file o URL. Il segreto sta nell'header
    X-BU-Segreto e non finisce mai nei log (si registra solo il tipo di errore).
    """
    try:
        url = os.environ.get(_N8N_URL_ENV, "").strip()
        segreto = os.environ.get(_N8N_SEGRETO_ENV, "")
        if not url or not segreto:
            log.debug("notifica n8n non configurata: salto")
            return
        risposta = requests.post(
            url,
            json={
                "codice": codice,
                "prodotto": prodotto,
                "ora": datetime.now(FUSO).isoformat(timespec="seconds"),
            },
            headers={"X-BU-Segreto": segreto},
            timeout=N8N_TIMEOUT_S,
            allow_redirects=False,  # il segreto non deve seguire un redirect
        )
        stato = risposta.status_code
        risposta.close()
        if stato >= 400:
            log.warning("notifica n8n rifiutata: codice=%s status=%d", codice, stato)
    except Exception as exc:  # noqa: BLE001 - la notifica non deve mai far danno
        log.warning(
            "notifica n8n fallita: codice=%s errore=%s", codice, type(exc).__name__
        )


def elimina_foto(
    prodotto: str | None,
    sessione: str | None,
    chiave: str | None,
    numero: int,
) -> dict:
    """Cancella la foto `numero` della sessione: solo i file f"{numero}_*" della sua
    cartella sotto questo prodotto, e solo se risolti dentro FOTO_DIR. La cartella,
    anche se resta vuota, non si tocca.

    Ritorna {"codice", "numero", "eliminata": True}; FotoNonTrovata se non c'è.
    """
    handle = valida_prodotto(prodotto)
    codice = verifica_sessione(sessione, chiave)
    numero = valida_numero(numero)
    radice = get_foto_dir()

    with _lock:
        cartella = trova_cartella(radice, handle, codice)
        if cartella is None:
            raise FotoNonTrovata("Foto non trovata")
        da_eliminare = [
            p
            for p in cartella.glob(f"{numero}_*")
            if p.is_file() and _dentro(p, radice)
        ]
        if not da_eliminare:
            raise FotoNonTrovata("Foto non trovata")
        for p in da_eliminare:
            p.unlink()

    return {"codice": codice, "numero": numero, "eliminata": True}
