"""Tests de la découpe locale sur une vidéo synthétique générée par ffmpeg.

La vidéo de test dure 20 s, avec une image-clé toutes les 5 s (GOP = 125 images
à 25 im/s) : cela rend visible la différence entre mode rapide et mode précis.
"""

import shutil
import subprocess

import pytest

from ciseau import cutter, ffmpeg

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")

FPS = 25
GOP = 125  # 5 s entre deux images-clés


@pytest.fixture(scope="module")
def video_test(tmp_path_factory):
    """Génère une fois pour toutes une vidéo de 20 s (mire + bip) avec GOP de 5 s."""
    chemin = tmp_path_factory.mktemp("video") / "source.mp4"
    subprocess.run(
        [
            ffmpeg.chemin_ffmpeg(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate={FPS}:duration=20",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
            "-c:v", "libx264", "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
            "-c:a", "aac", "-shortest", str(chemin),
        ],
        check=True,
    )
    return chemin


def test_duree_source(video_test):
    assert ffmpeg.duree(video_test) == pytest.approx(20, abs=0.2)


def test_images_cles_tous_les_5s(video_test):
    cles = ffmpeg.images_cles(video_test)
    if not cles:  # ffprobe absent : on ne peut pas vérifier
        pytest.skip("ffprobe absent")
    assert cles[:4] == pytest.approx([0, 5, 10, 15], abs=0.05)


def test_decoupe_precise(video_test, tmp_path):
    """Mode précis : durée exacte (7,3 s), quel que soit l'emplacement des images-clés."""
    sortie = cutter.decouper(video_test, 7.2, 14.5, tmp_path / "precis.mp4", mode="precis")
    assert sortie.exists()
    assert ffmpeg.duree(sortie) == pytest.approx(7.3, abs=0.1)


def test_decoupe_rapide(video_test, tmp_path):
    """Mode rapide : commence sur l'image-clé précédente (5 s), donc jusqu'à ~2,2 s de rab."""
    sortie = cutter.decouper(video_test, 7.2, 14.5, tmp_path / "rapide.mp4", mode="rapide")
    assert sortie.exists()
    d = ffmpeg.duree(sortie)
    # Jamais plus court que demandé (rien ne manque), au plus un GOP de plus.
    assert 7.3 - 0.1 <= d <= 7.3 + 5.0 + 0.5
    decalage = cutter.decalage_image_cle(video_test, 7.2)
    if decalage is not None:
        assert decalage == pytest.approx(2.2, abs=0.1)


def test_decoupe_audio(video_test, tmp_path):
    sortie = cutter.decouper(video_test, 3, 6, tmp_path / "son.m4a", mode="audio")
    assert sortie.exists()
    assert ffmpeg.duree(sortie) == pytest.approx(3, abs=0.15)


def test_decoupe_jusqua_la_fin(video_test, tmp_path):
    """fin=None : jusqu'au bout du fichier."""
    sortie = cutter.decouper(video_test, 15, None, tmp_path / "fin.mp4", mode="precis")
    assert ffmpeg.duree(sortie) == pytest.approx(5, abs=0.15)


def test_progression_appelee(video_test, tmp_path):
    fractions = []
    cutter.decouper(video_test, 0, 4, tmp_path / "p.mp4", mode="precis", sur_progression=fractions.append)
    assert fractions and fractions[-1] == 1.0
    assert all(0 <= f <= 1 for f in fractions)


def test_plage_invalide(video_test, tmp_path):
    with pytest.raises(Exception):
        cutter.decouper(video_test, 10, 5, tmp_path / "x.mp4")
