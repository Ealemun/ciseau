"""Tests du mode lot : lecture de la liste, traitement parallèle (serveur et ligne de commande)."""

import shutil
import subprocess
import sys
import time

import pytest

from ciseau import ffmpeg, lot, serveur as module_serveur
from ciseau.serveur import ServeurCiseau

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_serveur import attendre_fin, requete  # noqa: E402  (mêmes utilitaires HTTP)

avec_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


# ---------------------------------------------------------------------------
# Lecture de la liste
# ---------------------------------------------------------------------------

def test_lire_formats_acceptes():
    texte = """
    # commentaire ignoré
    https://www.youtube.com/watch?v=AAAA  1:23  1:45
    https://youtu.be/BBBB?t=90 - 2:30

    https://www.twitch.tv/videos/123\t1:02:00
    https://x.com/u/status/1, 10, 20
    https://vimeo.com/42;0:05;0:09
    https://www.youtube.com/watch?v=CCCC 1:23-1:45
    "D:\\Mes vidéos\\match 1.mp4" 10:00 12:00
    https://www.youtube.com/watch?v=DDDD
    """
    lignes = lot.lire(texte)
    resume = [(l.source, l.debut, l.fin) for l in lignes]
    assert resume == [
        ("https://www.youtube.com/watch?v=AAAA", "1:23", "1:45"),
        ("https://youtu.be/BBBB?t=90", None, "2:30"),
        ("https://www.twitch.tv/videos/123", "1:02:00", None),
        ("https://x.com/u/status/1", "10", "20"),
        ("https://vimeo.com/42", "0:05", "0:09"),
        ("https://www.youtube.com/watch?v=CCCC", "1:23", "1:45"),
        ("D:\\Mes vidéos\\match 1.mp4", "10:00", "12:00"),
        ("https://www.youtube.com/watch?v=DDDD", None, None),
    ]
    assert lignes[0].numero == 3  # numéros de ligne réels, pour les messages d'erreur


def test_lire_signale_toutes_les_erreurs():
    texte = "https://a 1:00 0:30\nhttps://b abc\nhttps://ok 1 2\nhttps://c 1 2 3\n"
    with pytest.raises(lot.ErreurLot) as exc:
        lot.lire(texte)
    message = str(exc.value)
    assert "ligne 1" in message and "ligne 2" in message and "ligne 4" in message
    assert "ligne 3" not in message


def test_lire_liste_vide():
    with pytest.raises(lot.ErreurLot):
        lot.lire("# rien\n\n")


# ---------------------------------------------------------------------------
# Serveur : plusieurs extraits en même temps
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def video_longue(tmp_path_factory):
    """Vidéo de 30 s en 720p : la découpe précise de 10 s prend un temps mesurable."""
    chemin = tmp_path_factory.mktemp("lot") / "source.mp4"
    subprocess.run([ffmpeg.chemin_ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=30",
                    "-f", "lavfi", "-i", "sine=duration=30", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(chemin)], check=True)
    return chemin


@avec_ffmpeg
def test_serveur_traite_en_parallele(tmp_path, video_longue, monkeypatch):
    srv = ServeurCiseau("127.0.0.1", 0, tmp_path / "extraits", paralleles=3)
    __import__("threading").Thread(target=srv.serve_forever, daemon=True).start()
    try:
        texte = "\n".join(f'"{video_longue}" {a} {a + 8}' for a in (0, 10, 20))
        statut, travaux = requete(srv, "POST", "/api/lot", {"texte": texte, "mode": "precis"})
        assert statut == 201 and len(travaux) == 3
        finis = [attendre_fin(srv, t["id"]) for t in travaux]
        assert all(t["statut"] == "termine" for t in finis), [t["erreur"] for t in finis]
        # Les trois ont démarré avant que le premier ne finisse : ils ont tourné ensemble.
        assert max(t["commence_le"] for t in finis) < min(t["termine_le"] for t in finis)
        assert all(t["rapport"]["methode"] == "ffmpeg" for t in finis)

        # Liste fautive : rien n'est ajouté, l'erreur nomme la ligne.
        statut, d = requete(srv, "POST", "/api/lot", {"texte": f'"{video_longue}" 5 1'})
        assert statut == 400 and "ligne 1" in d["erreur"]

        # Le bouton « Ouvrir le dossier » (POST JSON) est accepté.
        ouverts = []
        monkeypatch.setattr(module_serveur, "ouvrir_dossier", ouverts.append)
        statut, _ = requete(srv, "POST", f"/api/jobs/{finis[0]['id']}/dossier", {})
        assert statut == 200 and ouverts
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Ligne de commande : ciseau lot
# ---------------------------------------------------------------------------

@avec_ffmpeg
def test_cli_lot(tmp_path, video_longue):
    liste = tmp_path / "liste.txt"
    liste.write_text(f'# deux extraits\n"{video_longue}" 2 5\n"{video_longue}" 0:10 0:12.5\n', encoding="utf-8")
    t0 = time.monotonic()
    sortie = subprocess.run([sys.executable, "-m", "ciseau", "lot", str(liste), "-j", "2", "--rapide",
                             "-d", str(tmp_path / "out")], capture_output=True, text=True)
    assert sortie.returncode == 0, sortie.stderr
    fichiers = sorted((tmp_path / "out").glob("*.mp4"))
    assert len(fichiers) == 2
    assert "2 réussi(s), 0 échec(s)" in sortie.stderr
    assert time.monotonic() - t0 < 60


@avec_ffmpeg
def test_cli_lot_continue_apres_un_echec(tmp_path, video_longue):
    liste = tmp_path / "liste.txt"
    liste.write_text(f'"{tmp_path / "absent.mp4"}" 1 2\n"{video_longue}" 1 2\n', encoding="utf-8")
    sortie = subprocess.run([sys.executable, "-m", "ciseau", "lot", str(liste), "--rapide",
                             "-d", str(tmp_path / "out")], capture_output=True, text=True)
    assert sortie.returncode == 1
    assert "1 réussi(s), 1 échec(s)" in sortie.stderr
    assert len(list((tmp_path / "out").glob("*.mp4"))) == 1
