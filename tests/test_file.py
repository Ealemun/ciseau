"""Tests de l'annulation et du pilotage de la file de travaux.

Les extraits « longs » sont des découpes en mode précis d'une vidéo 720p :
le réencodage prend plusieurs secondes, ce qui laisse le temps d'agir.
"""

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from serveur_dash import ServeurDash  # noqa: E402
from test_segments import infos_youtube  # noqa: E402
from test_serveur import requete  # noqa: E402

from ciseau import downloader, ffmpeg, pipeline, resolver  # noqa: E402
from ciseau.annulation import Annulation  # noqa: E402
from ciseau.options import Options  # noqa: E402
from ciseau.serveur import FileDeTravaux, ServeurCiseau  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


@pytest.fixture(scope="module")
def video_lourde(tmp_path_factory):
    """60 s de 720p : en mode précis, réencoder 40 s prend plusieurs secondes."""
    chemin = tmp_path_factory.mktemp("file") / "lourde.mp4"
    subprocess.run([ffmpeg.chemin_ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=60",
                    "-f", "lavfi", "-i", "sine=duration=60", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(chemin)], check=True)
    return chemin


def attendre(condition, delai=30.0, pas=0.05):
    """Attend qu'une condition devienne vraie ; échoue au-delà du délai."""
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if condition():
            return
        time.sleep(pas)
    raise TimeoutError("condition jamais remplie")


def long(source):
    """Un extrait lent : 40 s réencodées en mode précis."""
    return {"source": str(source), "debut": 0, "fin": 40, "mode": "precis"}


def court(source):
    return {"source": str(source), "debut": 1, "fin": 2, "mode": "rapide"}


# ---------------------------------------------------------------------------
# ffmpeg interrompu
# ---------------------------------------------------------------------------

def test_executer_tue_ffmpeg(video_lourde, tmp_path):
    arret = threading.Event()
    threading.Timer(0.5, arret.set).start()
    t0 = time.monotonic()
    with pytest.raises(Annulation):
        ffmpeg.executer(["-y", "-i", str(video_lourde), "-c:v", "libx264", "-preset", "slow",
                         str(tmp_path / "x.mp4")], arret=arret)
    assert time.monotonic() - t0 < 3


# ---------------------------------------------------------------------------
# File de travaux
# ---------------------------------------------------------------------------

def test_annuler_en_attente_puis_en_cours(tmp_path, video_lourde):
    file = FileDeTravaux(tmp_path, paralleles=1)
    a = file.ajouter(long(video_lourde))
    b = file.ajouter(court(video_lourde))
    attendre(lambda: a.statut == "en_cours")

    # B attend derrière A : on l'annule, il ne démarrera jamais.
    file.annuler(b.id)
    assert b.statut == "annule" and b.commence_le is None

    # A est en plein réencodage : l'annulation l'arrête vite et ne laisse pas de fichier.
    attendre(lambda: a.progression is not None and a.progression > 0)
    t0 = time.monotonic()
    file.annuler(a.id)
    attendre(lambda: a.statut == "annule", delai=5)
    assert time.monotonic() - t0 < 3
    assert not list(tmp_path.glob("*.mp4"))

    # On ne peut pas annuler ce qui est déjà fini.
    with pytest.raises(ValueError):
        file.annuler(a.id)


def test_passer_en_premier(tmp_path, video_lourde):
    file = FileDeTravaux(tmp_path, paralleles=1)
    a = file.ajouter(long(video_lourde))
    b = file.ajouter(court(video_lourde))
    c = file.ajouter(court(video_lourde))
    attendre(lambda: a.statut == "en_cours")
    assert [t["rang"] for t in file.tous() if t["id"] in (b.id, c.id)] == [2, 1]  # tous() : récents d'abord

    file.prioriser(c.id)
    rangs = {t["id"]: t["rang"] for t in file.tous()}
    assert rangs[c.id] == 1 and rangs[b.id] == 2

    file.annuler(a.id)  # libère la place : C doit partir avant B
    attendre(lambda: b.statut == "termine" and c.statut == "termine")
    assert c.commence_le < b.commence_le


def test_annuler_tout_ce_qui_attend(tmp_path, video_lourde):
    file = FileDeTravaux(tmp_path, paralleles=1)
    a = file.ajouter(long(video_lourde))
    attente = [file.ajouter(court(video_lourde)) for _ in range(4)]
    attendre(lambda: a.statut == "en_cours")
    assert file.annuler_attente() == 4
    assert all(t.statut == "annule" for t in attente)
    assert a.statut == "en_cours"  # celui en cours continue
    file.annuler(a.id)
    attendre(lambda: a.statut == "annule")


def test_regler_paralleles_a_chaud(tmp_path, video_lourde):
    file = FileDeTravaux(tmp_path, paralleles=1)
    travaux = [file.ajouter(long(video_lourde)) for _ in range(3)]
    attendre(lambda: travaux[0].statut == "en_cours")
    time.sleep(0.3)
    assert [t.statut for t in travaux[1:]] == ["en_attente", "en_attente"]

    assert file.regler_paralleles(3) == 3
    attendre(lambda: all(t.statut == "en_cours" for t in travaux), delai=5)

    # Bornes : de 1 à 8.
    assert file.regler_paralleles(0) == 1
    assert file.regler_paralleles(50) == 8
    for t in travaux:
        file.annuler(t.id)
    attendre(lambda: all(t.statut == "annule" for t in travaux))


def test_routes_de_pilotage(tmp_path, video_lourde):
    srv = ServeurCiseau("127.0.0.1", 0, tmp_path, paralleles=1)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _, a = requete(srv, "POST", "/api/jobs", long(video_lourde))
        _, b = requete(srv, "POST", "/api/jobs", court(video_lourde))
        _, c = requete(srv, "POST", "/api/jobs", court(video_lourde))
        assert a["mode"] == "precis"
        assert requete(srv, "POST", f"/api/jobs/{c['id']}/priorite", {})[0] == 200
        assert requete(srv, "POST", "/api/paralleles", {"n": 2})[1] == {"paralleles": 2}
        assert requete(srv, "GET", "/api/version")[1]["paralleles"] == 2
        assert requete(srv, "POST", f"/api/jobs/{a['id']}/annuler", {})[0] == 200
        statut, d = requete(srv, "POST", "/api/jobs/inconnu/annuler", {})
        assert statut == 400 and "inconnu" in d["erreur"]
        # Sans mode précisé, un extrait part en mode rapide.
        _, e = requete(srv, "POST", "/api/jobs", {"source": str(video_lourde), "debut": 1, "fin": 2})
        assert e["mode"] == "rapide"
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Annulation pendant un téléchargement par segments
# ---------------------------------------------------------------------------

def test_annulation_pendant_le_telechargement(tmp_path, tmp_path_factory, monkeypatch):
    """L'annulation arrête les segments et ne déclenche PAS le repli sur yt-dlp."""
    # Une vidéo DASH servie très lentement : le téléchargement dure longtemps.
    d = tmp_path_factory.mktemp("lent")
    dash = ["-movflags", "+frag_keyframe+empty_moov+default_base_moof+global_sidx", "-f", "mp4"]
    ff = ffmpeg.chemin_ffmpeg()
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=20",
                    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "2M", "-g", "25", "-an", *dash,
                    str(d / "video.mp4")], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=20",
                    "-c:a", "aac", *dash, str(d / "audio.m4a")], check=True)
    srv = ServeurDash(d, debit_bride=200 * 1024, tout_brider=True).demarrer()
    try:
        monkeypatch.setattr(resolver, "infos_brutes", lambda *a, **k: infos_youtube(srv.url))

        def interdit(*a, **k):
            raise AssertionError("le repli yt-dlp ne doit pas être tenté après une annulation")
        monkeypatch.setattr(downloader, "_par_ytdlp", interdit)

        arret = threading.Event()
        threading.Timer(1.0, arret.set).start()
        t0 = time.monotonic()
        with pytest.raises(Annulation):
            pipeline.extraire("https://www.youtube.com/watch?v=abc123", 0, 20,
                              Options(dossier_sortie=tmp_path, connexions=2), arret=arret)
        assert time.monotonic() - t0 < 10
        assert not list(tmp_path.glob(".ciseau-tmp-*"))  # dossier temporaire nettoyé
        assert not list(tmp_path.glob("*.mp4"))
    finally:
        srv.arreter()
