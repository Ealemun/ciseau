"""Tests du téléchargement par segments (segments.py) et de son intégration.

On simule YouTube sans réseau :
- des fichiers DASH MP4 (ftyp | moov | sidx | moof mdat…) générés par ffmpeg ;
- servis par tests/serveur_dash.py, qui accepte les plages d'octets ;
- et des métadonnées « comme yt-dlp » dont les formats pointent vers ce serveur
  (on remplace resolver.infos_brutes, donc yt-dlp n'est pas nécessaire).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # pour importer serveur_dash
from serveur_dash import ServeurDash  # noqa: E402

from ciseau import downloader, ffmpeg, pipeline, resolver, segments  # noqa: E402
from ciseau.options import Options  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")

DUREE = 40  # secondes de vidéo de test
DASH = ["-movflags", "+frag_keyframe+empty_moov+default_base_moof+global_sidx", "-f", "mp4"]


# ---------------------------------------------------------------------------
# Fichiers et serveur
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dossier_dash(tmp_path_factory):
    """Un flux vidéo H.264 (image-clé toutes les 2 s) et un flux audio AAC, au format DASH.

    La vidéo est volontairement lourde (~20 Mo) pour dépasser un morceau de 10 Mo.
    """
    d = tmp_path_factory.mktemp("dash")
    ff = ffmpeg.chemin_ffmpeg()
    subprocess.run([ff, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=25:duration={DUREE}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "4M",
                    "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-an", *DASH,
                    str(d / "video.mp4")], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={DUREE}",
                    "-c:a", "aac", "-b:a", "128k", "-frag_duration", "10000000", *DASH,
                    str(d / "audio.m4a")], check=True)
    # Un flux WebM (non géré par la méthode rapide) pour tester le repli.
    (d / "video.webm").write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 1000)
    return d


@pytest.fixture
def serveur(dossier_dash):
    srv = ServeurDash(dossier_dash).demarrer()
    yield srv
    srv.arreter()


def infos_youtube(url_base: str, video_ext: str = "mp4") -> dict:
    """Métadonnées dans le format de yt-dlp, comme pour une vidéo YouTube."""
    video = {
        "format_id": "136", "url": f"{url_base}/video.{video_ext}", "protocol": "https",
        "ext": video_ext, "vcodec": "avc1.64001f" if video_ext == "mp4" else "vp9",
        "acodec": "none", "height": 720, "fps": 25, "tbr": 4000,
        "http_headers": {"User-Agent": "test"},
    }
    return {
        "id": "abc123", "title": "Vidéo de test", "duration": DUREE, "extractor_key": "Youtube",
        "formats": [
            {"format_id": "140", "url": f"{url_base}/audio.m4a", "protocol": "https", "ext": "m4a",
             "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128, "http_headers": {"User-Agent": "test"}},
            # Un flux audio plus faible, qui ne doit pas être choisi.
            {"format_id": "139", "url": f"{url_base}/audio.m4a", "protocol": "https", "ext": "m4a",
             "vcodec": "none", "acodec": "mp4a.40.5", "abr": 48},
            video,
            # Une définition supérieure en VP9 : à ignorer (la méthode rapide veut du H.264).
            {"format_id": "248", "url": f"{url_base}/video.webm", "protocol": "https", "ext": "webm",
             "vcodec": "vp9", "acodec": "none", "height": 1080},
        ],
    }


@pytest.fixture
def faux_youtube(serveur, monkeypatch):
    """Remplace yt-dlp par des métadonnées pointant vers le serveur de test."""
    infos = {"valeur": infos_youtube(serveur.url)}
    appels = []

    def fausses_infos(source, options=None, rafraichir=False):
        appels.append(source)
        return infos["valeur"]

    monkeypatch.setattr(resolver, "infos_brutes", fausses_infos)
    return infos, appels


def plages_demandees(srv: ServeurDash) -> list[tuple[int, int]]:
    """Plages (a, b) reçues par le serveur ; échoue si une requête était sans fin."""
    plages = []
    for r in srv.requetes:
        m = re.fullmatch(r"bytes=(\d+)-(\d+)", r)
        assert m, f"requête non bornée (YouTube la briderait) : {r!r}"
        plages.append((int(m.group(1)), int(m.group(2))))
    return plages


# ---------------------------------------------------------------------------
# Index et téléchargement d'une plage
# ---------------------------------------------------------------------------

def test_lire_index(serveur, dossier_dash):
    index, entete = segments.lire_index(f"{serveur.url}/video.mp4", {})
    s = index.segments
    assert entete[4:8] == b"ftyp" and len(entete) == index.fin_entete
    assert len(s) == DUREE // 2  # une image-clé (donc un segment) toutes les 2 s
    assert s[0].debut == 0 and s[-1].fin == pytest.approx(DUREE, abs=0.05)
    # Segments contigus, en temps comme en octets, jusqu'à la fin du fichier.
    for x, y in zip(s, s[1:]):
        assert x.fin == pytest.approx(y.debut) and x.octet_b + 1 == y.octet_a
    # Après le dernier segment, ffmpeg ajoute une petite boîte d'index final (mfra).
    reste = (dossier_dash / "video.mp4").read_bytes()[s[-1].octet_b + 1:]
    assert reste[4:8] == b"mfra"


def test_ne_telecharge_que_l_utile(serveur, dossier_dash, tmp_path):
    """Extraire 5 s au milieu ne doit pas tout télécharger."""
    plage = segments.telecharger_plage(f"{serveur.url}/video.mp4", {}, 21.3, 26.0, tmp_path / "v.mp4")
    assert plage.origine == pytest.approx(20.0)  # segment contenant 21,3 s
    taille_totale = (dossier_dash / "video.mp4").stat().st_size
    assert serveur.octets_envoyes < taille_totale / 4
    # Segments 20-22, 22-24, 24-26 : le fichier garde les horodatages d'origine,
    # donc sa « durée » affichée va jusqu'à 26 s et il démarre à 20 s.
    debut_flux = subprocess.run(
        [ffmpeg.chemin_ffprobe(), "-v", "error", "-show_entries", "format=start_time",
         "-of", "csv=p=0", str(plage.chemin)], capture_output=True, text=True, check=True).stdout
    assert float(debut_flux) == pytest.approx(20.0, abs=0.05)
    assert ffmpeg.duree(plage.chemin) == pytest.approx(26.0, abs=0.1)
    plages_demandees(serveur)


def test_morceaux_de_10_mo_au_plus(serveur, dossier_dash, tmp_path):
    """Plage > 10 Mo : découpée en plusieurs requêtes bornées de 10 Mo au plus."""
    taille_totale = (dossier_dash / "video.mp4").stat().st_size
    assert taille_totale > segments.TAILLE_MORCEAU, "vidéo de test trop petite pour ce test"
    segments.telecharger_plage(f"{serveur.url}/video.mp4", {}, 0, DUREE, tmp_path / "v.mp4", connexions=3)
    plages = plages_demandees(serveur)
    assert all(b - a + 1 <= segments.TAILLE_MORCEAU for a, b in plages)
    assert len(plages) >= 3  # index + au moins deux morceaux


def test_refus_du_serveur(serveur, tmp_path):
    with pytest.raises(segments.SegmentsIndisponibles):
        segments.telecharger_plage(f"{serveur.url}/absent.mp4", {}, 0, 5, tmp_path / "x.mp4")


def test_fichier_sans_index(serveur, tmp_path):
    with pytest.raises(segments.SegmentsIndisponibles):
        segments.lire_index(f"{serveur.url}/video.webm", {})


def test_choisir_formats():
    infos = infos_youtube("http://x")
    # Pièges : une piste doublée, une piste DRC et un flux endommagé, tous « meilleurs ».
    infos["formats"] += [
        {"format_id": "140-1", "url": "http://x/a", "protocol": "https", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a.40.2", "abr": 256, "language_preference": -1},
        {"format_id": "140-drc", "url": "http://x/a", "protocol": "https", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a.40.2", "abr": 256},
        {"format_id": "137", "url": "http://x/v", "protocol": "https", "ext": "mp4", "vcodec": "avc1.640028",
         "acodec": "none", "height": 1080, "preference": -10, "format_note": "1080p, DAMAGED"},
    ]
    video, audio = segments.choisir_formats(infos, "precis", None)
    assert video["format_id"] == "136" and audio["format_id"] == "140"
    assert segments.choisir_formats(infos, "audio", None)[0] is None
    with pytest.raises(segments.SegmentsIndisponibles):
        segments.choisir_formats(infos, "precis", 480)  # rien en H.264 sous 480p


# ---------------------------------------------------------------------------
# Intégration : pipeline complet sur une « vidéo YouTube »
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode, duree_attendue, tolerance", [
    ("precis", 7.5, 0.1),
    ("rapide", 9.0, 0.6),   # démarre sur l'image-clé de 12 s : 1,5 s de rab
    ("audio", 7.5, 0.1),
])
def test_pipeline_youtube_par_segments(faux_youtube, serveur, tmp_path, mode, duree_attendue, tolerance):
    resultat = pipeline.extraire("https://www.youtube.com/watch?v=abc123", "0:13.5", "0:21",
                                 Options(mode=mode, dossier_sortie=tmp_path))
    assert resultat.rapport["methode"] == "segments"
    assert resultat.fichier.exists() and resultat.fichier.suffix == (".m4a" if mode == "audio" else ".mp4")
    assert ffmpeg.duree(resultat.fichier) == pytest.approx(duree_attendue, abs=tolerance)
    assert {"analyse", "telechargement", "decoupe", "total", "octets"} <= resultat.rapport.keys()
    plages_demandees(serveur)  # aucune requête non bornée
    # Le dossier temporaire a disparu.
    assert not list(tmp_path.glob(".ciseau-tmp-*"))


def test_une_seule_extraction_par_extrait(faux_youtube, tmp_path):
    """Analyse + téléchargement ne doivent interroger les métadonnées qu'à travers le cache."""
    _, appels = faux_youtube
    pipeline.extraire("https://www.youtube.com/watch?v=abc123", 2, 4, Options(dossier_sortie=tmp_path))
    # Deux lectures (analyse, téléchargement) qui, en vrai, tombent dans le cache de infos_brutes.
    assert len(appels) == 2


def test_repli_sur_ytdlp_si_format_inadapte(faux_youtube, serveur, tmp_path, monkeypatch):
    """Que du VP9/WebM : la méthode rapide s'écarte et yt-dlp prend le relais."""
    infos, _ = faux_youtube
    infos["valeur"] = {**infos["valeur"],
                       "formats": [f for f in infos["valeur"]["formats"] if f["ext"] != "mp4"]}
    appels = []

    def faux_ytdlp(info, debut, fin, destination, options, dire, rapport, arret=None):
        appels.append((debut, fin))
        rapport["methode"] = "yt-dlp"
        destination.write_bytes(b"")
        return destination

    monkeypatch.setattr(downloader, "_par_ytdlp", faux_ytdlp)
    resultat = pipeline.extraire("https://www.youtube.com/watch?v=abc123", 5, 9, Options(dossier_sortie=tmp_path))
    assert appels == [(5.0, 9.0)]
    assert resultat.rapport["methode"] == "yt-dlp" and "H.264" in resultat.rapport["repli"]


# ---------------------------------------------------------------------------
# Cache des métadonnées
# ---------------------------------------------------------------------------

def test_cache_infos_brutes(monkeypatch):
    """Deux appels pour la même vidéo : yt-dlp n'est interrogé qu'une fois."""
    extractions = []

    class FauxYDL:
        def __init__(self, params):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            extractions.append(url)
            return {"id": "x", "title": "t", "duration": 10, "formats": []}

    faux_module = type(sys)("yt_dlp")
    faux_module.YoutubeDL = FauxYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", faux_module)
    url = "https://www.youtube.com/watch?v=cache"
    resolver.oublier(url)
    resolver.infos_brutes(url)
    resolver.infos_brutes(url)
    assert extractions == [url]
    resolver.oublier(url)
    resolver.infos_brutes(url)
    assert len(extractions) == 2
    resolver.oublier(url)
