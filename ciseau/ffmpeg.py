"""Localisation et pilotage de ffmpeg / ffprobe.

Ce module est la seule porte d'entrée vers les binaires ffmpeg : le reste du
code ne construit jamais de ligne de commande ffmpeg lui-même sans passer ici.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path


class FFmpegIntrouvable(RuntimeError):
    """ffmpeg (ou ffprobe) n'est pas installé ou pas dans le PATH."""


# Variables d'environnement pour forcer un emplacement précis des binaires.
ENV_FFMPEG = "EXTRAIT_FFMPEG"
ENV_FFPROBE = "EXTRAIT_FFPROBE"


def chemin_ffmpeg() -> str:
    """Renvoie le chemin de ffmpeg (variable d'env, sinon PATH), ou lève FFmpegIntrouvable."""
    candidat = os.environ.get(ENV_FFMPEG) or shutil.which("ffmpeg")
    if not candidat:
        raise FFmpegIntrouvable(
            "ffmpeg est introuvable. Installe-le (winget install Gyan.FFmpeg / brew install ffmpeg / "
            f"apt install ffmpeg) ou indique son chemin dans la variable {ENV_FFMPEG}."
        )
    return candidat


def chemin_ffprobe() -> str | None:
    """Renvoie le chemin de ffprobe, ou None s'il manque (on sait s'en passer)."""
    candidat = os.environ.get(ENV_FFPROBE) or shutil.which("ffprobe")
    if candidat:
        return candidat
    # ffprobe est en général installé à côté de ffmpeg : on tente ce voisin.
    try:
        voisin = Path(chemin_ffmpeg()).with_name("ffprobe" + Path(chemin_ffmpeg()).suffix)
    except FFmpegIntrouvable:
        return None
    return str(voisin) if voisin.exists() else None


# ---------------------------------------------------------------------------
# Paramètres d'encodage vidéo
# ---------------------------------------------------------------------------

# Encodeurs reconnus et les options de qualité qui vont avec. `libx264` marche
# partout ; les autres exploitent la carte graphique et sont bien plus rapides.
ENCODEURS: dict[str, list[str]] = {
    # CPU, universel. crf 18 = visuellement sans perte, preset rapide.
    "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"],
    # NVIDIA (Windows/Linux). cq joue le rôle de crf.
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
    # Apple Silicon / macOS.
    "h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-q:v", "65"],
    # Intel QuickSync.
    "h264_qsv": ["-c:v", "h264_qsv", "-global_quality", "20"],
    # AMD (Windows).
    "h264_amf": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"],
}

ENCODEUR_DEFAUT = "libx264"


def args_encodage(encodeur: str = ENCODEUR_DEFAUT) -> list[str]:
    """Options ffmpeg de sortie pour réencoder la vidéo + l'audio en AAC.

    Utilisé par la découpe précise (cutter.py) et par le téléchargement précis
    (downloader.py) pour garantir exactement le même rendu dans les deux cas.
    """
    if encodeur not in ENCODEURS:
        raise ValueError(f"encodeur inconnu : {encodeur!r} (choix : {', '.join(ENCODEURS)})")
    return [*ENCODEURS[encodeur], "-c:a", "aac", "-b:a", "192k"]


# ---------------------------------------------------------------------------
# Exécution avec suivi de progression
# ---------------------------------------------------------------------------

Progression = Callable[[float], None]  # reçoit une fraction entre 0 et 1


def executer(
    args: list[str],
    duree_attendue: float | None = None,
    sur_progression: Progression | None = None,
    arret: threading.Event | None = None,
) -> None:
    """Lance ffmpeg avec `args` (sans le binaire) et attend la fin.

    Si `duree_attendue` et `sur_progression` sont fournis, lit la sortie
    `-progress` de ffmpeg pour appeler `sur_progression(fraction)` au fil de l'eau.
    Si `arret` est levé pendant l'exécution, ffmpeg est tué et Annulation levée.
    Lève RuntimeError avec les dernières lignes de stderr si ffmpeg échoue.
    """
    from .annulation import Annulation, verifier

    verifier(arret)
    commande = [chemin_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    suivre = sur_progression is not None and duree_attendue
    if suivre:
        # -progress pipe:1 écrit des couples clé=valeur sur stdout, dont out_time_us.
        commande += ["-progress", "pipe:1"]
    commande += args

    proc = subprocess.Popen(
        commande,
        stdout=subprocess.PIPE if suivre else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # Surveillant : tue ffmpeg dès que l'arrêt est demandé. Il se termine de
    # lui-même quand ffmpeg a fini (vérification toutes les 0,2 s).
    tue = threading.Event()
    if arret is not None:
        def surveiller() -> None:
            while proc.poll() is None:
                if arret.wait(0.2):
                    tue.set()
                    proc.kill()
                    return
        threading.Thread(target=surveiller, name="ciseau-arret-ffmpeg", daemon=True).start()

    if suivre and proc.stdout is not None:
        for ligne in proc.stdout:
            # ffmpeg émet "out_time_us=12345678" (microsecondes déjà encodées).
            if ligne.startswith("out_time_us="):
                try:
                    secondes = int(ligne.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                sur_progression(min(1.0, max(0.0, secondes / duree_attendue)))  # type: ignore[arg-type]

    _, erreurs = proc.communicate()
    if tue.is_set():
        raise Annulation()
    if proc.returncode != 0:
        dernieres = "\n".join(erreurs.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg a échoué (code {proc.returncode}) :\n{dernieres}")
    if sur_progression:
        sur_progression(1.0)


# ---------------------------------------------------------------------------
# Lecture d'informations sur un fichier
# ---------------------------------------------------------------------------

_RE_DUREE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def duree(fichier: str | Path) -> float:
    """Durée d'un fichier média en secondes.

    Passe par ffprobe (JSON) quand il existe, sinon lit la ligne "Duration:" de ffmpeg.
    """
    fichier = str(fichier)
    probe = chemin_ffprobe()
    if probe:
        sortie = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", fichier],
            capture_output=True, text=True, check=True,
        ).stdout
        return float(json.loads(sortie)["format"]["duration"])

    # Repli : ffmpeg -i affiche la durée sur stderr puis sort en erreur (pas de sortie demandée).
    resultat = subprocess.run(
        [chemin_ffmpeg(), "-hide_banner", "-i", fichier], capture_output=True, text=True
    )
    m = _RE_DUREE.search(resultat.stderr)
    if not m:
        raise RuntimeError(f"impossible de lire la durée de {fichier}")
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def images_cles(fichier: str | Path, limite: float | None = None) -> list[float]:
    """Instants (en secondes) des images-clés vidéo du fichier.

    Sert à expliquer où tombera une découpe "rapide" et préparera le futur
    mode "smart cut". Nécessite ffprobe ; renvoie [] s'il manque.
    `limite` arrête la lecture après cet instant pour aller plus vite.
    """
    probe = chemin_ffprobe()
    if not probe:
        return []
    commande = [probe, "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey"]
    if limite is not None:
        commande += ["-read_intervals", f"%+{limite}"]
    commande += ["-show_entries", "frame=pts_time", "-of", "csv=p=0", str(fichier)]
    sortie = subprocess.run(commande, capture_output=True, text=True, check=True).stdout
    instants = []
    for ligne in sortie.splitlines():
        ligne = ligne.strip().rstrip(",")
        if ligne:
            try:
                instants.append(float(ligne))
            except ValueError:
                pass
    return instants
