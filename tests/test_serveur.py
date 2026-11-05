"""Tests du serveur local : verrous de sécurité, travaux de bout en bout, liens directs.

Chaque test démarre un vrai ServeurCiseau sur un port libre (port 0) dans un thread.
"""

import functools
import http.client
import http.server
import json
import shutil
import subprocess
import threading
import time

import pytest

from ciseau import ffmpeg
from ciseau.serveur import ServeurCiseau

avec_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def serveur(tmp_path):
    """Un serveur ciseau sur un port libre, arrêté à la fin du test."""
    srv = ServeurCiseau("127.0.0.1", 0, tmp_path / "extraits")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="module")
def dossier_media(tmp_path_factory):
    """Dossier contenant une vidéo de 12 s, index en tête (lisible en HTTP sans Range)."""
    dossier = tmp_path_factory.mktemp("media")
    if shutil.which("ffmpeg"):
        subprocess.run(
            [ffmpeg.chemin_ffmpeg(), "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=12",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
             "-c:v", "libx264", "-g", "50", "-c:a", "aac", "-shortest",
             "-movflags", "+faststart", str(dossier / "clip.mp4")],
            check=True,
        )
    return dossier


@pytest.fixture
def serveur_http_media(dossier_media):
    """Petit serveur HTTP statique qui sert dossier_media (simule un site distant)."""
    class Silencieux(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # pas de journal dans la sortie des tests
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Silencieux, directory=str(dossier_media))
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def requete(srv, methode, chemin, corps=None, entetes=None):
    """Envoie une requête au serveur ciseau ; renvoie (statut, json)."""
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    tetes = {"Host": f"127.0.0.1:{port}"}
    donnees = None
    if corps is not None:
        donnees = json.dumps(corps).encode()
        tetes["Content-Type"] = "application/json"
    tetes.update(entetes or {})
    conn.request(methode, chemin, body=donnees, headers=tetes)
    rep = conn.getresponse()
    brut = rep.read()
    conn.close()
    try:
        return rep.status, json.loads(brut) if brut else None
    except json.JSONDecodeError:
        return rep.status, brut


def attendre_fin(srv, ident, delai=60):
    """Attend qu'un travail soit terminé (ou en erreur) et le renvoie."""
    limite = time.time() + delai
    while time.time() < limite:
        _, t = requete(srv, "GET", f"/api/jobs/{ident}")
        if t["statut"] in ("termine", "erreur"):
            return t
        time.sleep(0.2)
    raise TimeoutError(ident)


# ---------------------------------------------------------------------------
# Sécurité
# ---------------------------------------------------------------------------

def test_version_accessible(serveur):
    statut, d = requete(serveur, "GET", "/api/version")
    assert statut == 200 and "version" in d


def test_refuse_hote_etranger(serveur):
    """DNS rebinding : un Host qui n'est pas la machine locale est refusé."""
    statut, _ = requete(serveur, "GET", "/api/jobs", entetes={"Host": "evil.example:80"})
    assert statut == 403


def test_refuse_origine_site_web(serveur):
    statut, _ = requete(serveur, "POST", "/api/jobs", {"source": "x"},
                        entetes={"Origin": "https://evil.example"})
    assert statut == 403


def test_refuse_post_sans_json(serveur):
    """Une page web peut envoyer un POST text/plain sans requête préalable : refusé."""
    port = serveur.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/jobs", body='{"source":"x"}',
                 headers={"Host": f"127.0.0.1:{port}", "Content-Type": "text/plain"})
    assert conn.getresponse().status == 403


def test_preflight_cors_refuse(serveur):
    statut, _ = requete(serveur, "OPTIONS", "/api/jobs",
                        entetes={"Origin": "https://evil.example"})
    assert statut == 403


def test_accepte_extension_et_interface(serveur):
    port = serveur.server_address[1]
    for origine in ("chrome-extension://abcdefghijklmnop", "moz-extension://1234",
                    f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
        statut, _ = requete(serveur, "GET", "/api/jobs", entetes={"Origin": origine})
        assert statut == 200, origine


def test_source_manquante(serveur):
    statut, d = requete(serveur, "POST", "/api/jobs", {"source": "  "})
    assert statut == 400 and "source" in d["erreur"]


# ---------------------------------------------------------------------------
# Travaux de bout en bout
# ---------------------------------------------------------------------------

@avec_ffmpeg
def test_travail_fichier_local_debut_zero(serveur, dossier_media):
    """Un début à 0 doit rester 0 (régression : `0 or None`)."""
    statut, t = requete(serveur, "POST", "/api/jobs",
                        {"source": str(dossier_media / "clip.mp4"), "debut": 0, "fin": 3, "mode": "precis"})
    assert statut == 201 and t["debut"] == 0
    fini = attendre_fin(serveur, t["id"])
    assert fini["statut"] == "termine", fini["erreur"]
    assert ffmpeg.duree(fini["fichier"]) == pytest.approx(3, abs=0.15)


@avec_ffmpeg
def test_lien_direct_http(serveur, serveur_http_media):
    """Lien direct vers un .mp4 : découpe par ffmpeg à distance, sans yt-dlp."""
    url = f"{serveur_http_media}/clip.mp4"
    statut, info = requete(serveur, "POST", "/api/info", {"source": url})
    assert statut == 200, info
    assert info["site"] == "direct" and info["duree"] == pytest.approx(12, abs=0.2)

    # Mode précis explicite : le mode par défaut (rapide) démarrerait sur l'image-clé précédente.
    _, t = requete(serveur, "POST", "/api/jobs", {"source": url, "debut": "0:04", "fin": "0:07.5", "mode": "precis"})
    fini = attendre_fin(serveur, t["id"])
    assert fini["statut"] == "termine", fini["erreur"]
    assert ffmpeg.duree(fini["fichier"]) == pytest.approx(3.5, abs=0.15)


# ---------------------------------------------------------------------------
# Choix du port au démarrage
# ---------------------------------------------------------------------------

def test_port_occupe_on_prend_le_suivant(tmp_path):
    """Un autre programme sur le port demandé : ciseau démarre sur le suivant."""
    import socket

    from ciseau import serveur as module

    occupant = socket.socket()
    occupant.bind(("127.0.0.1", 0))
    occupant.listen()
    port = occupant.getsockname()[1]
    try:
        srv, url = module.demarrer(port, tmp_path)
        try:
            assert srv is not None and srv.server_address[1] > port
            assert url == f"http://127.0.0.1:{srv.server_address[1]}/"
        finally:
            srv.server_close()
    finally:
        occupant.close()


def test_ciseau_deja_lance_reutilise(serveur, tmp_path):
    """Second lancement : pas de second serveur, on réutilise celui qui tourne."""
    from ciseau import serveur as module

    port = serveur.server_address[1]
    assert module.ciseau_deja_lance(port)
    srv, url = module.demarrer(port, tmp_path)
    assert srv is None and url == f"http://127.0.0.1:{port}/"


def test_version_identifie_ciseau(serveur):
    _, d = requete(serveur, "GET", "/api/version")
    assert d["application"] == "ciseau"
