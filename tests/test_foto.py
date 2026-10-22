"""Test di POST /foto e POST /foto/elimina (foto dei clienti Bimbi Unici): servizio
esposto su internet."""

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
SEGRETO_TEST = "segreto-di-test-lungo-almeno-32-caratteri!"
PRODOTTO = "ritratto-da-foto-in-rilievo"
EMAIL = "mamma@example.com"
GB = 1024**3
DiskUsage = namedtuple("DiskUsage", "total used free")


def _immagine(formato: str, size=(64, 48), **kw) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buf, format=formato, **kw)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("FOTO_DIR", str(tmp_path))
    monkeypatch.setenv("FOTO_SEGRETO", SEGRETO_TEST)
    # Spazio libero deterministico (il disco di sviluppo potrebbe essere sotto i 10 GB).
    monkeypatch.setattr(
        foto_clienti.shutil, "disk_usage", lambda _p: DiskUsage(10**12, 0, 10**12)
    )
    foto_clienti.limiter.reset()
    foto_clienti.limiter_elimina.reset()
    yield
    foto_clienti.limiter.reset()
    foto_clienti.limiter_elimina.reset()


@pytest.fixture
def client():
    return TestClient(app)


def _post(
    client,
    data: bytes,
    nome="foto.jpg",
    prodotto=PRODOTTO,
    sessione=None,
    chiave=None,
    email=EMAIL,
):
    form = {"prodotto": prodotto}
    if email is not None:
        form["email"] = email
    if sessione is not None:
        form["sessione"] = sessione
    if chiave is not None:
        form["chiave"] = chiave
    return client.post("/foto", data=form, files={"file": (nome, data, "image/jpeg")})


def _post_xff(client, data: bytes, xff: str):
    return client.post(
        "/foto",
        data={"prodotto": PRODOTTO, "email": EMAIL},
        files={"file": ("a.jpg", data, "image/jpeg")},
        headers={"X-Forwarded-For": xff},
    )


def _elimina(client, sessione, chiave, numero, prodotto=PRODOTTO):
    form = {
        "prodotto": prodotto,
        "sessione": sessione,
        "chiave": chiave,
        "numero": str(numero),
    }
    return client.post("/foto/elimina", data=form)


def _file_salvati(tmp_path):
    return sorted(p for p in tmp_path.rglob("*") if p.is_file())


def _solo_foto(tmp_path):
    return [p for p in _file_salvati(tmp_path) if p.name != "contatto.txt"]


def _istantanea(tmp_path) -> dict:
    """Percorso relativo -> sha256 di ogni file: per verificare che nulla cambi."""
    return {
        p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in _file_salvati(tmp_path)
    }


def _sessione(client, n_foto=1, prodotto=PRODOTTO):
    """Apre una sessione con `n_foto` foto; ritorna (codice, chiave, cartella)."""
    r = _post(client, _immagine("JPEG"), prodotto=prodotto)
    assert r.status_code == 200
    codice, chiave = r.json()["codice"], r.json()["chiave"]
    for _ in range(n_foto - 1):
        r = _post(
            client, _immagine("JPEG"), prodotto=prodotto, sessione=codice, chiave=chiave
        )
        assert r.status_code == 200
    radice = foto_clienti.get_foto_dir()
    cartella = foto_clienti.trova_cartella(radice, prodotto, codice)
    assert cartella is not None
    return codice, chiave, cartella


def _numeri(cartella):
    return sorted(
        int(p.name.split("_")[0]) for p in cartella.iterdir() if p.name[0].isdigit()
    )


# 1) JPEG valido ------------------------------------------------------------ #
def test_jpeg_valido_salvato_con_byte_identici(client, tmp_path):
    data = _immagine("JPEG")
    nome = "La mia_foto è bella.JPG"
    r = _post(client, data, nome=nome, prodotto="ritratto-di-coppia")
    assert r.status_code == 200
    body = r.json()
    assert CODICE_RE.match(body["codice"])
    assert body["numero"] == 1
    assert body["chiave"] == foto_clienti.chiave_sessione(body["codice"])
    assert re.fullmatch(r"[0-9a-f]{32}", body["chiave"])
    assert body["nome"] == nome
    assert body["byte"] == len(data)

    # una foto sola, niente sidecar (solo il contatto del cliente accanto):
    # prodotto, mese, codice e numero nel percorso
    salvati = _file_salvati(tmp_path)
    assert [p.name for p in salvati if p.name != "contatto.txt"] == [
        "1_La-mia-foto-e-bella.jpg"
    ]
    assert len(salvati) == 2
    jpg = _solo_foto(tmp_path)[0]
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    assert jpg.relative_to(tmp_path).parts == (
        "ritratto-di-coppia",
        f"{ora:%Y-%m}",
        body["codice"],
        "1_La-mia-foto-e-bella.jpg",
    )
    sha = hashlib.sha256(data).hexdigest()
    assert hashlib.sha256(jpg.read_bytes()).hexdigest() == sha


def test_file_esistente_mai_sovrascritto_ne_cancellato(tmp_path, monkeypatch):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    cartella = tmp_path / PRODOTTO / f"{ora:%Y-%m}" / "F-0101-AAAAA"
    cartella.mkdir(parents=True)
    altrui = cartella / "1_foto.jpg"
    altrui.write_bytes(b"foto di un altro cliente")
    monkeypatch.setattr(foto_clienti, "genera_codice", lambda *_: "F-0101-AAAAA")
    monkeypatch.setattr(foto_clienti, "_prossimo_numero", lambda _c: 1)
    with pytest.raises(FileExistsError):
        foto_clienti.salva_foto(_immagine("JPEG"), "foto.jpg", PRODOTTO, email=EMAIL)
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
    salvati = list(tmp_path.glob(f"{PRODOTTO}/*/*/1_IMG-0001.heic"))
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
    assert len(list(tmp_path.glob(f"{PRODOTTO}/*/*/*.{ext}"))) == 1


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
    assert len(_solo_foto(tmp_path)) == 1  # solo la foto del primo upload


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
@pytest.mark.parametrize("percorso", ["/foto", "/foto/elimina"])
def test_preflight_origine_ammessa(client, percorso):
    r = client.options(
        percorso,
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
def test_ventunesima_richiesta_429(client):
    assert foto_clienti.RATE_PER_IP_ORA == 20
    assert foto_clienti.RATE_TOTALE_GIORNO == 200
    data = _immagine("JPEG")
    for _ in range(20):
        assert _post(client, data).status_code == 200
    assert _post(client, data).status_code == 429


def test_rate_limit_per_ip_indipendente(client):
    data = _immagine("JPEG")
    for _ in range(foto_clienti.RATE_PER_IP_ORA):
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
        (tmp_path / PRODOTTO / f"{ora:%Y-%m}" / codice).mkdir(parents=True)
    assert len(codici) == 200


def test_codice_gia_esistente_viene_rigenerato(tmp_path, monkeypatch):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    (tmp_path / PRODOTTO / "2026-10" / "F-0101-AAAAA").mkdir(parents=True)
    sequenza = iter(["F-0101-AAAAA", "F-0101-BBBBB"])
    monkeypatch.setattr(foto_clienti, "_codice_casuale", lambda *_: next(sequenza))
    assert foto_clienti.genera_codice(ora, tmp_path) == "F-0101-BBBBB"


def test_vecchio_file_piatto_codice_non_riusato(tmp_path, monkeypatch):
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    mese = tmp_path / PRODOTTO / "2026-07"
    mese.mkdir(parents=True)
    (mese / "20260714-1200_F-0714-K7M2X_foto.jpg").write_bytes(b"vecchia foto")
    sequenza = iter(["F-0714-K7M2X", "F-0714-ZZZZZ"])
    monkeypatch.setattr(foto_clienti, "_codice_casuale", lambda *_: next(sequenza))
    assert foto_clienti.genera_codice(ora, tmp_path) == "F-0714-ZZZZZ"


def test_codice_usato_in_altro_prodotto_o_anno_non_riusato(tmp_path, monkeypatch):
    # La chiave dipende solo dal codice: riassegnarlo (stesso MMGG l'anno dopo, o
    # sotto un altro prodotto) aprirebbe le foto di un cliente a un altro.
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    (tmp_path / "disegno-dei-nonni" / "2025-10" / "F-1016-AAAAA").mkdir(parents=True)
    sequenza = iter(["F-1016-AAAAA", "F-1016-BBBBB"])
    monkeypatch.setattr(foto_clienti, "_codice_casuale", lambda *_: next(sequenza))
    assert foto_clienti.genera_codice(ora, tmp_path) == "F-1016-BBBBB"


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
    for i in range(foto_clienti.RATE_PER_IP_ORA):
        assert _post_xff(client, data, f"9.9.9.{i}").status_code == 200
    assert _post_xff(client, data, "9.9.9.99").status_code == 429


def test_xff_dal_proxy_separa_i_clienti():
    proxy = TestClient(app, client=("172.18.0.5", 4000))
    data = _immagine("JPEG")
    for _ in range(foto_clienti.RATE_PER_IP_ORA):
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
        assert p.relative_to(tmp_path).parts[0] == PRODOTTO


def test_nessun_get_su_foto(client):
    assert client.get("/foto").status_code == 405
    assert client.get("/foto/elimina").status_code == 405
    rotte = [r for r in app.routes if getattr(r, "path", "").startswith("/foto")]
    assert {r.path for r in rotte} == {"/foto", "/foto/elimina"}
    assert all(r.methods <= {"POST"} for r in rotte)


# 11) Sessione: più foto per carrello ----------------------------------------- #
def test_seconda_foto_stessa_cartella_numero_2(client, tmp_path):
    codice, chiave, cartella = _sessione(client)
    data = _immagine("PNG")
    r = _post(client, data, nome="seconda.png", sessione=codice, chiave=chiave)
    assert r.status_code == 200
    body = r.json()
    assert (body["codice"], body["numero"], body["chiave"]) == (codice, 2, chiave)
    seconda = cartella / "2_seconda.png"
    assert (
        hashlib.sha256(seconda.read_bytes()).hexdigest()
        == hashlib.sha256(data).hexdigest()
    )
    assert len(_solo_foto(tmp_path)) == 2  # tutte nella stessa cartella
    assert {p.parent for p in _file_salvati(tmp_path)} == {cartella}


def test_settima_foto_409_nessun_file_in_piu(client, tmp_path):
    assert foto_clienti.MAX_FOTO == 6
    codice, chiave, cartella = _sessione(client, n_foto=6)
    prima = _istantanea(tmp_path)
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 409
    assert _istantanea(tmp_path) == prima


def test_dopo_cancellazione_si_puo_ricaricare_fino_a_6(client):
    codice, chiave, cartella = _sessione(client, n_foto=6)
    assert _elimina(client, codice, chiave, 6).status_code == 200
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200
    assert r.json()["numero"] == 6
    assert (
        _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave).status_code
        == 409
    )


def test_numero_oltre_99_rifiutato_ogni_foto_resta_cancellabile(client):
    codice, chiave, cartella = _sessione(client)
    (cartella / "1_foto.jpg").rename(cartella / "99_foto.jpg")
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 409
    assert _numeri(cartella) == [99]


def test_sessione_con_chiave_ma_senza_cartella_la_crea_nel_mese(client, tmp_path):
    codice = "F-1016-7K3QX"
    chiave = foto_clienti.chiave_sessione(codice)
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200
    assert (r.json()["codice"], r.json()["numero"]) == (codice, 1)
    ora = foto_clienti.datetime.now(foto_clienti.FUSO)
    assert (tmp_path / PRODOTTO / f"{ora:%Y-%m}" / codice / "1_foto.jpg").is_file()


def test_sessione_continuata_nel_mese_dopo_resta_nel_mese_di_creazione(
    client, tmp_path, monkeypatch
):
    vera = foto_clienti.datetime

    def orologio(momento):
        monkeypatch.setattr(
            foto_clienti, "datetime", type("D", (), {"now": lambda _tz: momento})
        )

    orologio(vera(2026, 10, 31, 23, 50, tzinfo=foto_clienti.FUSO))
    r = _post(client, _immagine("JPEG"))
    assert r.status_code == 200
    codice, chiave = r.json()["codice"], r.json()["chiave"]
    assert codice.startswith("F-1031-")

    orologio(vera(2026, 11, 1, 0, 10, tzinfo=foto_clienti.FUSO))
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200
    assert r.json()["numero"] == 2
    assert sorted(p.name for p in (tmp_path / PRODOTTO).iterdir()) == ["2026-10"]
    assert _numeri(tmp_path / PRODOTTO / "2026-10" / codice) == [1, 2]


def test_sessione_di_altro_prodotto_crea_nel_prodotto_richiesto(client, tmp_path):
    # La chiave dipende solo dal codice, quindi è valida anche con un altro prodotto.
    # Comportamento voluto: la cartella si cerca SOLO sotto il prodotto richiesto;
    # non trovandola se ne crea una nuova lì. Nell'altro prodotto non si scrive né
    # si cancella mai.
    codice, chiave, cartella_a = _sessione(client, prodotto="ritratto-di-coppia")
    prima_a = {p.name: p.read_bytes() for p in cartella_a.iterdir()}

    r = _post(
        client,
        _immagine("PNG"),
        prodotto="disegno-dei-nonni",
        sessione=codice,
        chiave=chiave,
    )
    assert r.status_code == 200
    assert (r.json()["codice"], r.json()["numero"]) == (codice, 1)
    cartella_b = foto_clienti.trova_cartella(tmp_path, "disegno-dei-nonni", codice)
    assert cartella_b is not None and cartella_b != cartella_a
    assert _numeri(cartella_b) == [1]

    assert (
        _elimina(client, codice, chiave, 1, prodotto="disegno-dei-nonni").status_code
        == 200
    )
    assert {p.name: p.read_bytes() for p in cartella_a.iterdir()} == prima_a
    assert [p.name for p in cartella_b.iterdir()] == ["contatto.txt"]


def test_cancellazione_con_prodotto_sbagliato_404_non_tocca_nulla(client, tmp_path):
    codice, chiave, _cartella = _sessione(client, prodotto="ritratto-di-coppia")
    prima = _istantanea(tmp_path)
    assert (
        _elimina(client, codice, chiave, 1, prodotto="disegno-dei-nonni").status_code
        == 404
    )
    assert _istantanea(tmp_path) == prima


# 12) Chiave e segreto --------------------------------------------------------- #
@pytest.mark.parametrize("chiave", ["0" * 32, "", "è" * 32, None])
def test_chiave_sbagliata_403_su_aggiunta(client, tmp_path, chiave):
    codice, giusta, _cartella = _sessione(client)
    prima = _istantanea(tmp_path)
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 403
    assert _istantanea(tmp_path) == prima


@pytest.mark.parametrize("chiave", ["0" * 32, "", "è" * 32])
def test_chiave_sbagliata_403_su_cancellazione(client, tmp_path, chiave):
    codice, _giusta, _cartella = _sessione(client)
    prima = _istantanea(tmp_path)
    r = _elimina(client, codice, chiave, 1)
    assert r.status_code in (403, 422)  # "" è rifiutato già come campo mancante
    if chiave:
        assert r.status_code == 403
    assert _istantanea(tmp_path) == prima


def test_chiave_di_un_altro_codice_403(client, tmp_path):
    codice_a, _chiave_a, _ = _sessione(client)
    _codice_b, chiave_b, _ = _sessione(client)
    prima = _istantanea(tmp_path)
    assert (
        _post(client, _immagine("JPEG"), sessione=codice_a, chiave=chiave_b).status_code
        == 403
    )
    assert _elimina(client, codice_a, chiave_b, 1).status_code == 403
    assert _istantanea(tmp_path) == prima


def test_chiave_e_hmac_del_codice():
    import hmac as hmac_mod

    attesa = hmac_mod.new(SEGRETO_TEST.encode(), b"F-1016-7K3QX", hashlib.sha256)
    assert foto_clienti.chiave_sessione("F-1016-7K3QX") == attesa.hexdigest()[:32]


@pytest.mark.parametrize("segreto", [None, "", "x" * 31])
def test_segreto_assente_o_corto(client, tmp_path, monkeypatch, segreto):
    if segreto is None:
        monkeypatch.delenv("FOTO_SEGRETO")
    else:
        monkeypatch.setenv("FOTO_SEGRETO", segreto)
    # Il tema di oggi (solo file + prodotto) continua a funzionare.
    r = _post(client, _immagine("JPEG"))
    assert r.status_code == 200
    body = r.json()
    assert body["chiave"] is None
    assert body["numero"] == 1
    prima = _istantanea(tmp_path)
    # Tutto ciò che richiede la chiave risponde 503, senza toccare file.
    r = _post(client, _immagine("JPEG"), sessione=body["codice"], chiave="0" * 32)
    assert r.status_code == 503
    assert _elimina(client, body["codice"], "0" * 32, 1).status_code == 503
    assert _istantanea(tmp_path) == prima


def test_segreto_da_32_caratteri_basta(monkeypatch):
    monkeypatch.setenv("FOTO_SEGRETO", "x" * 32)
    assert foto_clienti.chiave_sessione("F-1016-7K3QX") is not None


# 13) Sessione malformata ------------------------------------------------------ #
SESSIONI_MALFORMATE = [
    "../x",
    "F-1016-7K3QX/..",
    "f-1016-7k3qx",
    "*",
    "F-1016-7K3Q*",
    "F-1016-7K3QO",  # O non è nell'alfabeto
    "F-1016-7K3QX\n",
    "../../F-1016-7K3QX",
]


@pytest.mark.parametrize("sessione", SESSIONI_MALFORMATE)
def test_sessione_malformata_400_su_aggiunta(client, tmp_path, sessione):
    r = _post(client, _immagine("JPEG"), sessione=sessione, chiave="0" * 32)
    assert r.status_code == 400
    assert _file_salvati(tmp_path) == []
    assert list(tmp_path.iterdir()) == []  # nemmeno cartelle


@pytest.mark.parametrize("sessione", SESSIONI_MALFORMATE)
def test_sessione_malformata_400_su_cancellazione(client, tmp_path, sessione):
    _sessione(client, n_foto=2)
    prima = _istantanea(tmp_path)
    r = _elimina(client, sessione, "0" * 32, 1)
    assert r.status_code == 400
    assert _istantanea(tmp_path) == prima


def test_sessione_malformata_400_anche_senza_segreto(client, monkeypatch):
    monkeypatch.delenv("FOTO_SEGRETO")
    assert (
        _post(client, _immagine("JPEG"), sessione="../x", chiave="x").status_code == 400
    )


# 14) Cancellazione ------------------------------------------------------------ #
def test_cancellazione_toglie_solo_quel_numero(client, tmp_path):
    codice, chiave, cartella = _sessione(client, n_foto=3)
    altri = {
        p.name: p.read_bytes()
        for p in cartella.iterdir()
        if not p.name.startswith("2_")
    }
    r = _elimina(client, codice, chiave, 2)
    assert r.status_code == 200
    assert r.json() == {"codice": codice, "numero": 2, "eliminata": True}
    assert {p.name: p.read_bytes() for p in cartella.iterdir()} == altri


def test_cancellato_il_2_la_successiva_e_4(client):
    codice, chiave, cartella = _sessione(client, n_foto=3)
    assert _elimina(client, codice, chiave, 2).status_code == 200
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.json()["numero"] == 4
    assert _numeri(cartella) == [1, 3, 4]


def test_cancellato_il_3_la_successiva_e_3(client):
    codice, chiave, cartella = _sessione(client, n_foto=3)
    assert _elimina(client, codice, chiave, 3).status_code == 200
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.json()["numero"] == 3
    assert _numeri(cartella) == [1, 2, 3]


def test_cancellare_1_non_tocca_11(client):
    codice, chiave, cartella = _sessione(client)
    (cartella / "11_foto.jpg").write_bytes(b"undici")
    assert _elimina(client, codice, chiave, 1).status_code == 200
    assert sorted(p.name for p in cartella.iterdir()) == [
        "11_foto.jpg",
        "contatto.txt",
    ]


def test_symlink_verso_fuori_foto_dir_non_cancellato(client, tmp_path_factory):
    codice, chiave, cartella = _sessione(client)
    fuori = tmp_path_factory.mktemp("fuori") / "segreto.txt"
    fuori.write_bytes(b"non toccare")
    try:
        (cartella / "2_link.jpg").symlink_to(fuori)
    except OSError:
        pytest.skip("symlink non disponibili su questo sistema")
    assert _elimina(client, codice, chiave, 2).status_code == 404
    assert fuori.read_bytes() == b"non toccare"
    assert (cartella / "2_link.jpg").is_symlink()


def test_cartella_vuota_resta(client):
    codice, chiave, cartella = _sessione(client)
    assert _elimina(client, codice, chiave, 1).status_code == 200
    assert cartella.is_dir()
    assert [p.name for p in cartella.iterdir()] == ["contatto.txt"]
    # e la sessione continua a funzionare: n riparte da 1
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.json()["numero"] == 1


def test_numero_inesistente_404(client, tmp_path):
    codice, chiave, _cartella = _sessione(client, n_foto=2)
    prima = _istantanea(tmp_path)
    assert _elimina(client, codice, chiave, 5).status_code == 404
    assert _istantanea(tmp_path) == prima


def test_sessione_senza_cartella_404(client, tmp_path):
    codice = "F-1016-7K3QX"
    r = _elimina(client, codice, foto_clienti.chiave_sessione(codice), 1)
    assert r.status_code == 404
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "numero", ["0", "-1", "100", "1/../x", "*", "1_*", "", "1.5", "abc"]
)
def test_numero_non_valido_rifiutato_senza_toccare_nulla(client, tmp_path, numero):
    codice, chiave, _cartella = _sessione(client, n_foto=3)
    prima = _istantanea(tmp_path)
    r = _elimina(client, codice, chiave, numero)
    assert r.status_code in (400, 422)
    assert _istantanea(tmp_path) == prima


@pytest.mark.parametrize("numero", [0, -1, 100, "1", 1.0, True, None])
def test_valida_numero_difesa_in_profondita(numero):
    with pytest.raises(foto_clienti.NumeroNonValido):
        foto_clienti.valida_numero(numero)


def test_elimina_foto_logica_rifiuta_numero_non_valido(client, tmp_path):
    codice, chiave, _cartella = _sessione(client)
    prima = _istantanea(tmp_path)
    with pytest.raises(foto_clienti.NumeroNonValido):
        foto_clienti.elimina_foto(PRODOTTO, codice, chiave, "1_*")
    assert _istantanea(tmp_path) == prima


# 15) Rate limit cancellazioni -------------------------------------------------- #
def test_rate_limit_cancellazioni_valori():
    assert foto_clienti.limiter_elimina.per_ip_ora == 30
    assert foto_clienti.limiter_elimina.totale_giorno == 500
    assert foto_clienti.limiter_elimina is not foto_clienti.limiter


def test_caricamenti_esauriti_cancellazione_funziona(client):
    codice, chiave, _cartella = _sessione(client, n_foto=2)
    data = _immagine("JPEG")
    while _post(client, data).status_code == 200:
        pass
    assert _post(client, data).status_code == 429
    assert _elimina(client, codice, chiave, 2).status_code == 200


def test_cancellazioni_esaurite_caricamento_funziona(client, monkeypatch):
    codice, chiave, _cartella = _sessione(client)
    monkeypatch.setattr(foto_clienti.limiter_elimina, "per_ip_ora", 3)
    for _ in range(3):
        assert _elimina(client, codice, chiave, 9).status_code == 404
    assert _elimina(client, codice, chiave, 1).status_code == 429
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200


def test_trentunesima_cancellazione_429(client):
    codice, chiave, _cartella = _sessione(client)
    for _ in range(30):
        assert _elimina(client, codice, chiave, 9).status_code == 404
    assert _elimina(client, codice, chiave, 1).status_code == 429


# 16) Email obbligatoria e contatto.txt ----------------------------------------- #
def _contatto(cartella) -> str:
    return (cartella / "contatto.txt").read_text(encoding="utf-8")


def _righe_contatto(cartella) -> dict:
    return dict(r.split(": ", 1) for r in _contatto(cartella).splitlines())


def _orologio(monkeypatch, momento):
    monkeypatch.setattr(
        foto_clienti, "datetime", type("D", (), {"now": lambda _tz: momento})
    )


def test_email_mancante_400_nulla_su_disco(client, tmp_path):
    r = _post(client, _immagine("JPEG"), email=None)
    assert r.status_code == 400
    assert r.json() == {"errore": "email"}
    assert list(tmp_path.iterdir()) == []  # nemmeno la cartella del prodotto


def test_email_mancante_su_aggiunta_400_nulla_cambia(client, tmp_path):
    codice, chiave, _cartella = _sessione(client)
    prima = _istantanea(tmp_path)
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave, email=None)
    assert r.status_code == 400
    assert r.json() == {"errore": "email"}
    assert _istantanea(tmp_path) == prima


EMAIL_NON_VALIDE = [
    "",
    "   ",
    "senza-chiocciola.it",
    "con spazio@example.com",
    "mamma@exa mple.com",
    "mamma@example.com\nBcc: x@y.it",
    "mamma@example.com\r\nBcc: x@y.it",
    "ma\tmma@example.com",
    "ma\x00mma@example.com",
    "a@@example.com",
    "a@b@example.com",
    "@example.com",
    "mamma@",
    "mamma@localhost",
    "mamma@.com",
    "mamma@example.",
    "mamma@example..com",
    "x" * 65 + "@example.com",
    "a@" + "b" * 250 + ".it",
]


@pytest.mark.parametrize("email", EMAIL_NON_VALIDE)
def test_email_non_valida_400_nulla_su_disco(client, tmp_path, email):
    r = _post(client, _immagine("JPEG"), email=email)
    assert r.status_code == 400
    assert r.json() == {"errore": "email"}
    assert list(tmp_path.iterdir()) == []


def test_email_lunga_254_ok_255_no(client):
    dominio = ".".join(["d" * 50] * 3) + ".it"
    ok = "a" * 64 + "@" + dominio
    ok += "x" * (254 - len(ok))
    assert len(ok) == 254
    assert _post(client, _immagine("JPEG"), email=ok).status_code == 200
    assert _post(client, _immagine("JPEG"), email=ok + "x").status_code == 400


def test_email_parte_locale_64_ok(client):
    r = _post(client, _immagine("JPEG"), email="a" * 64 + "@example.com")
    assert r.status_code == 200


def test_errore_email_porta_header_cors(client):
    r = client.post(
        "/foto",
        data={"prodotto": PRODOTTO},
        files={"file": ("a.jpg", _immagine("JPEG"), "image/jpeg")},
        headers={"Origin": ORIGINE_OK},
    )
    assert r.status_code == 400
    assert r.headers.get("access-control-allow-origin") == ORIGINE_OK


def test_prima_foto_scrive_contatto_con_i_4_campi(client, tmp_path):
    r = _post(client, _immagine("JPEG"), email=EMAIL)
    assert r.status_code == 200
    codice = r.json()["codice"]
    cartella = foto_clienti.trova_cartella(tmp_path, PRODOTTO, codice)
    righe = _righe_contatto(cartella)
    assert list(righe) == ["email", "codice", "prodotto", "aggiornato"]
    assert righe["email"] == EMAIL
    assert righe["codice"] == codice
    assert righe["prodotto"] == PRODOTTO
    aggiornato = foto_clienti.datetime.fromisoformat(righe["aggiornato"])
    assert aggiornato.utcoffset() is not None  # fuso esplicito (Europe/Rome)
    assert _contatto(cartella).endswith("\n")
    assert [p.name for p in cartella.iterdir() if p.name.startswith(".")] == []


def test_email_normalizzata_strip_e_dominio_minuscolo(client, tmp_path):
    r = _post(client, _immagine("JPEG"), email="  Mamma.Rossi@Example.COM ")
    assert r.status_code == 200
    cartella = foto_clienti.trova_cartella(tmp_path, PRODOTTO, r.json()["codice"])
    # la parte locale resta com'è: è case-sensitive per standard
    assert _righe_contatto(cartella)["email"] == "Mamma.Rossi@example.com"


def test_seconda_foto_stessa_mail_contatto_invariato(client):
    codice, chiave, cartella = _sessione(client)
    prima = (cartella / "contatto.txt").read_bytes()
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave, email=EMAIL)
    assert r.status_code == 200
    assert (cartella / "contatto.txt").read_bytes() == prima


def test_stessa_mail_con_dominio_maiuscolo_non_riscrive(client):
    codice, chiave, cartella = _sessione(client)
    prima = (cartella / "contatto.txt").read_bytes()
    r = _post(
        client,
        _immagine("JPEG"),
        sessione=codice,
        chiave=chiave,
        email=" mamma@EXAMPLE.com ",
    )
    assert r.status_code == 200
    assert (cartella / "contatto.txt").read_bytes() == prima


def test_seconda_foto_mail_diversa_aggiorna_contatto(client, monkeypatch):
    vera = foto_clienti.datetime
    _orologio(monkeypatch, vera(2026, 10, 22, 9, 0, tzinfo=foto_clienti.FUSO))
    codice, chiave, cartella = _sessione(client)
    prima = _righe_contatto(cartella)

    _orologio(monkeypatch, vera(2026, 10, 22, 9, 30, tzinfo=foto_clienti.FUSO))
    r = _post(
        client,
        _immagine("JPEG"),
        sessione=codice,
        chiave=chiave,
        email="papa@example.org",
    )
    assert r.status_code == 200
    dopo = _righe_contatto(cartella)
    assert dopo["email"] == "papa@example.org"
    assert (dopo["codice"], dopo["prodotto"]) == (prima["codice"], prima["prodotto"])
    assert dopo["aggiornato"] != prima["aggiornato"]
    assert dopo["aggiornato"].startswith("2026-10-22T09:30:00")
    assert [p.name for p in cartella.iterdir() if p.name.startswith(".")] == []


def test_aggiunta_con_cartella_nuova_scrive_contatto(client, tmp_path):
    # sessione + chiave validi ma cartella inesistente: si apre ora, col suo contatto
    codice = "F-1016-7K3QX"
    chiave = foto_clienti.chiave_sessione(codice)
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200
    cartella = foto_clienti.trova_cartella(tmp_path, PRODOTTO, codice)
    assert _righe_contatto(cartella)["email"] == EMAIL


def test_foto_rifiutata_non_tocca_il_contatto(client, tmp_path):
    codice, chiave, _cartella = _sessione(client, n_foto=6)
    prima = _istantanea(tmp_path)
    r = _post(
        client,
        _immagine("JPEG"),
        sessione=codice,
        chiave=chiave,
        email="altra@example.org",
    )
    assert r.status_code == 409
    assert _istantanea(tmp_path) == prima  # nemmeno la mail cambia
    r = _post(client, b"non una foto", sessione=codice, chiave=chiave, email="x@y.it")
    assert r.status_code == 415
    assert _istantanea(tmp_path) == prima


def test_contatto_non_conta_nel_limite_delle_6_foto(client, tmp_path):
    codice, chiave, cartella = _sessione(client, n_foto=6)
    assert (cartella / "contatto.txt").is_file()
    assert len(_solo_foto(tmp_path)) == 6
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 409


def test_sesta_foto_ok_con_contatto_presente(client):
    codice, chiave, cartella = _sessione(client, n_foto=5)
    assert (cartella / "contatto.txt").is_file()
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.status_code == 200
    assert r.json()["numero"] == 6


def test_numerazione_ignora_il_contatto(client):
    codice, chiave, cartella = _sessione(client, n_foto=3)
    assert _elimina(client, codice, chiave, 3).status_code == 200
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.json()["numero"] == 3
    assert _numeri(cartella) == [1, 2, 3]
    assert foto_clienti._prossimo_numero(cartella) == 4


def test_cartella_con_solo_contatto_riparte_da_1(client):
    codice, chiave, cartella = _sessione(client)
    assert _elimina(client, codice, chiave, 1).status_code == 200
    assert [p.name for p in cartella.iterdir()] == ["contatto.txt"]
    r = _post(client, _immagine("JPEG"), sessione=codice, chiave=chiave)
    assert r.json()["numero"] == 1


def test_elimina_non_tocca_il_contatto(client):
    codice, chiave, cartella = _sessione(client, n_foto=2)
    contatto = (cartella / "contatto.txt").read_bytes()
    assert _elimina(client, codice, chiave, 1).status_code == 200
    assert _elimina(client, codice, chiave, 2).status_code == 200
    assert (cartella / "contatto.txt").read_bytes() == contatto
    assert _elimina(client, codice, chiave, 1).status_code == 404
    assert (cartella / "contatto.txt").read_bytes() == contatto


@pytest.mark.parametrize("numero", ["contatto.txt", "contatto", "0", "*", "1_*"])
def test_elimina_non_accetta_il_nome_del_contatto(client, tmp_path, numero):
    codice, chiave, _cartella = _sessione(client)
    prima = _istantanea(tmp_path)
    r = _elimina(client, codice, chiave, numero)
    assert r.status_code in (400, 422)
    assert _istantanea(tmp_path) == prima


def test_nessun_endpoint_in_lettura_del_contatto(client):
    rotte = {r.path for r in app.routes if "foto" in getattr(r, "path", "")}
    assert rotte == {"/foto", "/foto/elimina"}
    assert client.get("/foto/contatto.txt").status_code in (404, 405)


def test_salva_foto_logica_richiede_email(tmp_path):
    with pytest.raises(foto_clienti.EmailNonValida):
        foto_clienti.salva_foto(_immagine("JPEG"), "a.jpg", PRODOTTO)
    assert list(tmp_path.iterdir()) == []


def test_contatto_scrittura_atomica_nessun_residuo(client):
    codice, chiave, cartella = _sessione(client)
    for i in range(3):
        _post(
            client,
            _immagine("JPEG"),
            sessione=codice,
            chiave=chiave,
            email=f"m{i}@example.com",
        )
    nomi = sorted(p.name for p in cartella.iterdir() if not p.name[0].isdigit())
    assert nomi == ["contatto.txt"]
    assert _righe_contatto(cartella)["email"] == "m2@example.com"
