"""Options communes à toute la chaîne (CLI -> pipeline -> downloader/cutter).

Regroupées dans une seule dataclass pour qu'un futur client (API web,
extension navigateur) n'ait qu'un objet à construire.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cutter import Mode
from .ffmpeg import ENCODEUR_DEFAUT


@dataclass
class Options:
    # Mode de découpe : "precis" par défaut (coupe à l'image près), "rapide" (copie
    # de flux, démarre sur l'image-clé précédente) ou "audio" (bande-son seule).
    mode: Mode = "precis"

    # Encodeur vidéo pour le mode précis (voir ffmpeg.ENCODEURS).
    encodeur: str = ENCODEUR_DEFAUT

    # Dossier où ranger les extraits quand aucun nom de fichier n'est imposé.
    dossier_sortie: Path = Path("extraits")

    # Chemin de sortie imposé (prioritaire sur dossier_sortie + nom automatique).
    fichier_sortie: Path | None = None

    # Hauteur vidéo maximale (ex. 1080) ; None = meilleure qualité disponible.
    hauteur_max: int | None = None

    # Cookies pour les sites qui l'exigent (YouTube "confirmez que vous n'êtes pas
    # un robot", vidéos privées…) : nom d'un navigateur au sens de yt-dlp
    # ("chrome", "firefox", "edge", "chrome:Profile 1"…) OU un fichier cookies.txt.
    cookies_navigateur: str | None = None
    cookies_fichier: Path | None = None

    # Connexions simultanées par flux pour le téléchargement par segments
    # (voir segments.py). 4 suffit à saturer la plupart des connexions sans
    # attirer l'attention de YouTube.
    connexions: int = 4

    # Affiche les journaux détaillés de yt-dlp/ffmpeg.
    verbeux: bool = False
