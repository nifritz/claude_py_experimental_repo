"""Test di POST /foto (foto dei clienti Bimbi Unici): servizio esposto su internet."""

import hashlib
import io
import re
from collections import namedtuple

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pillow_heif import register_heif_opener

from api_server import app
from scripts import foto_clienti

register_heif_opener()

ORIGINE_OK = "https://bimbiunici.it"
CODICE_RE = re.compile(r"^F-\d{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{5}$")
GB = 1024**3
DiskUsage = namedtuple("DiskUsage", "total used free")


def _immagine(formato: str, size=(64, 48), **kw) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buf, format=formato, **kw)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("FOTO_DIR", str(tmp_path))
    # Spazio libero deterministico (il disco di sviluppo potrebbe essere sotto i 10 GB).
    monkeypatch.setattr(
        foto_clienti.shutil, "disk_usage", lambda _p: DiskUsage(10**12, 0, 10**12)
    )
    foto_clienti.limiter.reset()
    yield
    foto_clienti.limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


def _post(client, data: bytes, nome="foto.jpg", prodotto="ritratto-da-foto-in-rilievo"):
    form = {"prodotto": prodotto}
    return client.post("/foto", data=form, files={"file": (nome, data, "image/jpeg")})


def _post_xff(client, data: bytes, xff: str):
    return client.post(
        "/foto",
        data={"prodotto": "ritratto-da-foto-in-rilievo"},
        files={"file": ("a.jpg", data, "image/jpeg")},
        headers={"X-Forwarded-For": xff},
    )


def _file_salvati(tmp_path):
    return [p for p in tmp_path.rglob("*") if p.is_file()]


# 1) JPEG valido ------------------------------------------------------------ #
def test_jpeg_valido_salvato_con_byte_identici(client, tmp_path):
    data = _immagine("JPEG")
    nome = "La mia_foto è bella.JPG"
    r = _post(client, data, nome=nome, prodotto="ritratto-di-coppia")
    assert r.status_code == 200
    body = r.json()
    assert CODICE_RE.match(body["codice"])
    assert body["codice"].startswith("F-")
    assert body["nome"] == nome
    assert body["byte"] == len(data)

    # un file solo, niente sidecar: data, codice e prodotto stanno nel percorso
    salvati = _file_salvati(tmp_path)
    assert len(salvati) == 1
    jpg = salvati[0]
    assert jpg.parent.parent.name == "ritratto-di-coppia"
    sha = hashlib.sha256(data).hexdigest()
    assert hashlib.sha256(jpg.read_bytes()).hexdigest() == sha
    assert re.fullmatch(
        rf"\d{{8}}-\d{{4}}_{body['codice']}_La-mia-foto-e-bella\.jpg", jpg.name
    )


def test_file_esistente_mai_sovrascritto_ne_cancellato(tmp_path, monkeypatch):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    mese = tmp_path / "ritratto-da-foto-in-rilievo" / f"{ora:%Y-%m}"
    mese.mkdir(parents=True)
    altrui = mese / f"{ora:%Y%m%d-%H%M}_F-0101-AAAAA_foto.jpg"
    altrui.write_bytes(b"foto di un altro cliente")
    monkeypatch.setattr(foto_clienti, "genera_codice", lambda *_: "F-0101-AAAAA")
    monkeypatch.setattr(
        foto_clienti, "datetime", type("D", (), {"now": lambda _tz: ora})
    )
    with pytest.raises(FileExistsError):
        foto_clienti.salva_foto(
            _immagine("JPEG"), "foto.jpg", "ritratto-da-foto-in-rilievo"
        )
    assert altrui.read_bytes() == b"foto di un altro cliente"


def test_ogni_prodotto_ha_la_sua_cartella(client, tmp_path):
    assert (
        _post(client, _immagine("JPEG"), prodotto="portafoto-battesimo").status_code
        == 200
    )
    assert (
        _post(client, _immagine("JPEG"), prodotto="disegno-dei-nonni").status_code
        == 200
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "disegno-dei-nonni",
        "portafoto-battesimo",
    ]


# 2) HEIC ------------------------------------------------------------------- #
def test_heic_valido_estensione_heic(client, tmp_path):
    data = _immagine("HEIF")
    r = _post(client, data, nome="IMG_0001.HEIC")
    assert r.status_code == 200
    salvati = list(tmp_path.glob("ritratto-da-foto-in-rilievo/*/*.heic"))
    assert len(salvati) == 1
    assert salvati[0].read_bytes() == data


@pytest.mark.parametrize(
    ("formato", "ext", "kw"),
    [
        ("PNG", "png", {}),
        ("WEBP", "webp", {}),
        ("MPO", "jpg", {"save_all": True}),
    ],
)
def test_altri_formati_ammessi(client, tmp_path, formato, ext, kw):
    # Il nome inviato mente (.txt): conta solo il contenuto.
    r = _post(client, _immagine(formato, **kw), nome="x.txt")
    assert r.status_code == 200
    assert len(list(tmp_path.glob(f"ritratto-da-foto-in-rilievo/*/*.{ext}"))) == 1


# 3) File troppo grande ------------------------------------------------------ #
def test_file_oltre_25mb_413_nessun_file(client, tmp_path):
    assert foto_clienti.MAX_BYTES == 26_214_400
    r = _post(client, b"x" * (foto_clienti.MAX_BYTES + 1))
    assert r.status_code == 413
    assert _file_salvati(tmp_path) == []


def test_limite_esatto(client, tmp_path, monkeypatch):
    data = _immagine("JPEG")
    monkeypatch.setattr(foto_clienti, "MAX_BYTES", len(data))
    assert _post(client, data).status_code == 200
    monkeypatch.setattr(foto_clienti, "MAX_BYTES", len(data) - 1)
    assert _post(client, data).status_code == 413
    assert len(_file_salvati(tmp_path)) == 1  # solo la foto del primo upload


# 4) Contenuto non immagine --------------------------------------------------- #
def test_testo_con_nome_jpg_415(client, tmp_path):
    r = _post(client, b"questo non e una foto", nome="foto.jpg")
    assert r.status_code == 415
    assert _file_salvati(tmp_path) == []


def test_file_vuoto_415(client):
    assert _post(client, b"").status_code == 415


def test_formato_immagine_non_ammesso_415(client):
    assert _post(client, _immagine("GIF"), nome="a.gif").status_code == 415
    assert _post(client, _immagine("BMP"), nome="a.bmp").status_code == 415


# 5) Prodotto = cartella: niente che esca da FOTO_DIR ------------------------- #
@pytest.mark.parametrize(
    "prodotto",
    [
        "..",
        "../ritratti",
        "",
        "Ritratto",
        "ritratto/..",
        "a.b",
        "-x",
        "a b",
        "x" * 81,
        "/etc",
    ],
)
def test_prodotto_non_valido_400(client, tmp_path, prodotto):
    r = _post(client, _immagine("JPEG"), prodotto=prodotto)
    assert r.status_code in (400, 422)  # "" è rifiutato già come campo mancante
    assert _file_salvati(tmp_path) == []


def test_prodotto_mancante_422(client, tmp_path):
    r = client.post("/foto", files={"file": ("a.jpg", _immagine("JPEG"), "image/jpeg")})
    assert r.status_code == 422
    assert _file_salvati(tmp_path) == []


def test_prodotto_non_valido_e_esattamente_400(client):
    assert _post(client, _immagine("JPEG"), prodotto="../x").status_code == 400


# 6) CORS -------------------------------------------------------------------- #
def test_preflight_origine_ammessa(client):
    r = client.options(
        "/foto",
        headers={"Origin": ORIGINE_OK, "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") == ORIGINE_OK
    assert "access-control-allow-credentials" not in r.headers


def test_preflight_origine_non_ammessa(client):
    r = client.options(
        "/foto",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in r.headers


def test_errori_portano_header_cors(client):
    # Il JS del tema deve poter leggere anche 400/415/429.
    r = client.post(
        "/foto",
        data={"prodotto": "../x"},
        files={"file": ("a.jpg", b"1", "image/jpeg")},
        headers={"Origin": ORIGINE_OK},
    )
    assert r.status_code == 400
    assert r.headers.get("access-control-allow-origin") == ORIGINE_OK


def test_chiamate_senza_origin_invariate(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


# 7) Rate limit --------------------------------------------------------------- #
def test_undicesima_richiesta_429(client):
    data = _immagine("JPEG")
    for _ in range(10):
        assert _post(client, data).status_code == 200
    assert _post(client, data).status_code == 429


def test_rate_limit_per_ip_indipendente(client):
    data = _immagine("JPEG")
    for _ in range(10):
        assert _post(client, data).status_code == 200
    altro = TestClient(app, client=("203.0.113.9", 5000))
    assert _post(altro, data).status_code == 200


def test_limite_giornaliero_totale(client, monkeypatch):
    data = _immagine("JPEG")
    monkeypatch.setattr(foto_clienti.limiter, "per_ip_ora", 10**6)
    monkeypatch.setattr(foto_clienti.limiter, "totale_giorno", 3)
    for _ in range(3):
        assert _post(client, data).status_code == 200
    assert _post(client, data).status_code == 429


def test_finestra_oraria_scorre():
    lim = foto_clienti.RateLimiter(per_ip_ora=2, totale_giorno=100)
    assert lim.consenti("a", ora=0)
    assert lim.consenti("a", ora=10)
    assert not lim.consenti("a", ora=20)
    assert lim.consenti("a", ora=3601)


# 8) Codici ------------------------------------------------------------------- #
def test_200_codici_unici_e_alfabeto(tmp_path):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    codici = set()
    for _ in range(200):
        codice = foto_clienti.genera_codice(ora, tmp_path)
        assert CODICE_RE.match(codice)
        assert codice[2:6] == f"{ora:%m%d}"
        assert not set(codice[7:]) & set("01OIL")
        codici.add(codice)
        (tmp_path / f"20260101-1200_{codice}_foto.jpg").touch()
    assert len(codici) == 200


def test_codice_gia_esistente_viene_rigenerato(tmp_path, monkeypatch):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    (tmp_path / "20260101-1200_F-0101-AAAAA_foto.jpg").touch()
    sequenza = iter(["F-0101-AAAAA", "F-0101-BBBBB"])
    monkeypatch.setattr(foto_clienti, "_codice_casuale", lambda *_: next(sequenza))
    assert foto_clienti.genera_codice(ora, tmp_path) == "F-0101-BBBBB"


# 9) Cartella del mese -------------------------------------------------------- #
def test_cartella_del_mese_creata_da_sola(client, tmp_path):
    assert list(tmp_path.iterdir()) == []
    assert (
        _post(client, _immagine("JPEG"), prodotto="disegno-dei-nonni").status_code
        == 200
    )
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    assert (tmp_path / "disegno-dei-nonni" / f"{ora:%Y-%m}").is_dir()


# 10) X-Forwarded-For ---------------------------------------------------------- #
def test_xff_ignorato_se_client_fuori_dalla_subnet():
    assert foto_clienti.ip_cliente("203.0.113.9", "1.2.3.4") == "203.0.113.9"
    assert foto_clienti.ip_cliente("172.19.0.2", "1.2.3.4") == "172.19.0.2"
    assert foto_clienti.ip_cliente("testclient", "1.2.3.4") == "testclient"


def test_xff_usato_dal_proxy_nella_subnet():
    assert foto_clienti.ip_cliente("172.18.0.5", "1.2.3.4, 172.18.0.5") == "1.2.3.4"
    assert foto_clienti.ip_cliente("172.18.0.5", None) == "172.18.0.5"
    assert foto_clienti.ip_cliente("172.18.0.5", "non-un-ip") == "172.18.0.5"


def test_xff_spoofato_da_fuori_subnet_non_aggira_il_limite(client):
    data = _immagine("JPEG")
    for i in range(10):
        assert _post_xff(client, data, f"9.9.9.{i}").status_code == 200
    assert _post_xff(client, data, "9.9.9.99").status_code == 429


def test_xff_dal_proxy_separa_i_clienti():
    proxy = TestClient(app, client=("172.18.0.5", 4000))
    data = _immagine("JPEG")
    for _ in range(10):
        assert _post_xff(proxy, data, "1.2.3.4").status_code == 200
    assert _post_xff(proxy, data, "1.2.3.4").status_code == 429
    assert _post_xff(proxy, data, "5.6.7.8").status_code == 200


# Disco ---------------------------------------------------------------------- #
def test_disco_sotto_10gb_507_nessun_file(client, tmp_path, monkeypatch):
    poco = DiskUsage(10**12, 10**12 - 5 * GB, 5 * GB)
    monkeypatch.setattr(foto_clienti.shutil, "disk_usage", lambda _p: poco)
    r = _post(client, _immagine("JPEG"))
    assert r.status_code == 507
    assert _file_salvati(tmp_path) == []


# Pulizia nome / sicurezza percorsi ---------------------------------------------- #
@pytest.mark.parametrize(
    ("inviato", "atteso"),
    [
        ("../../etc/passwd.jpg", "passwd"),
        ("C:\\Users\\x\\Foto Bimba_01.HEIC", "Foto-Bimba-01"),
        ("Città è così.png", "Citta-e-cosi"),
        ("", "foto"),
        (None, "foto"),
        ("....jpg", "foto"),
        ("a" * 100 + ".jpg", "a" * 40),
    ],
)
def test_pulisci_nome(inviato, atteso):
    assert foto_clienti.pulisci_nome(inviato) == atteso


def test_filename_malevolo_non_esce_dalla_cartella(client, tmp_path):
    r = _post(client, _immagine("JPEG"), nome="../../../../evil.jpg")
    assert r.status_code == 200
    salvati = _file_salvati(tmp_path)
    assert salvati
    for p in salvati:
        assert p.relative_to(tmp_path).parts[0] == "ritratto-da-foto-in-rilievo"


def test_nessun_get_su_foto(client):
    assert client.get("/foto").status_code == 405
    rotte = [r for r in app.routes if getattr(r, "path", "").startswith("/foto")]
    assert rotte
    assert all(r.methods <= {"POST"} for r in rotte)
