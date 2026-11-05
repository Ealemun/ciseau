"""Découpe d'un fichier vidéo local entre deux instants.

Deux modes, qui correspondent à un vrai compromis technique :

- "rapide"  : copie des flux sans réencodage (-c copy). Instantané et sans perte,
              mais la vidéo ne peut commencer que sur une image-clé : l'extrait
              démarre donc à l'image-clé *précédant* le début demandé (jusqu'à
              quelques secondes plus tôt selon la source). Rien ne manque, il y
              a juste un peu de rab au début.
- "precis"  : réencodage. ffmpeg décode depuis l'image-clé précédente et jette
              les images avant le début : la coupe est à l'image près au début
              comme à la fin. Plus lent (proportionnel à la durée de l'extrait),
              qualité pilotée par ffmpeg.args_encodage().

Le mode "audio" extrait seulement la bande-son (m4a/mp3), à l'instant près.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from . import ffmpeg
from .annulation import Annulation, Arret
from .timecode import valider_plage

Mode = Literal["rapide", "precis", "audio"]
MODES: tuple[str, ...] = ("rapide", "precis", "audio")

# Extensions de sortie par défaut selon le mode.
EXTENSION_PAR_MODE = {"rapide": ".mp4", "precis": ".mp4", "audio": ".m4a"}


def decouper(
    source: str | Path,
    debut: float,
    fin: float | None,
    destination: str | Path,
    mode: Mode = "precis",
    encodeur: str = ffmpeg.ENCODEUR_DEFAUT,
    sur_progression: ffmpeg.Progression | None = None,
    arret: Arret | None = None,
) -> Path:
    """Écrit dans `destination` l'extrait [debut, fin] de `source`. Renvoie le chemin écrit.

    `fin` à None = jusqu'à la fin du fichier.
    `source` peut aussi être une URL de média direct (https://…/video.mp4) :
    ffmpeg la lit alors à distance, en ne téléchargeant que la zone utile.
    """
    destination = Path(destination)
    distant = "://" in str(source)
    if not distant:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(source)
    if mode not in MODES:
        raise ValueError(f"mode inconnu : {mode!r} (choix : {', '.join(MODES)})")

    try:
        duree_source: float | None = ffmpeg.duree(source)
    except Exception:  # noqa: BLE001
        # Flux distant sans durée connue (direct HLS…) : on fait confiance à `fin`.
        if not distant or fin is None:
            raise
        duree_source = None
    valider_plage(debut, fin, duree_source)
    # Durée réellement demandée (bornée par la fin du fichier quand on la connaît).
    if fin is None:
        fin_effective = duree_source
    else:
        fin_effective = min(fin, duree_source) if duree_source is not None else fin
    duree_extrait = fin_effective - debut

    destination.parent.mkdir(parents=True, exist_ok=True)

    # `-ss` AVANT `-i` : ffmpeg saute directement à la zone voulue au lieu de
    # décoder depuis le début (crucial sur un fichier de plusieurs heures).
    # `-t` limite la durée de sortie.
    args: list[str] = ["-y", "-ss", f"{debut:.3f}", "-i", str(source), "-t", f"{duree_extrait:.3f}"]

    if mode == "rapide":
        # Copie des flux ; make_zero recale les timestamps négatifs issus du
        # rab avant le début (images entre l'image-clé et `debut`).
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    elif mode == "precis":
        args += ffmpeg.args_encodage(encodeur)
    else:  # audio
        args += ["-vn", "-c:a", "aac", "-b:a", "192k"]

    if destination.suffix.lower() in (".mp4", ".m4a", ".mov"):
        # Place l'index (moov) en tête : lecture possible avant la fin du téléchargement.
        args += ["-movflags", "+faststart"]

    args.append(str(destination))
    _executer_ou_nettoyer(args, duree_extrait, sur_progression, arret, destination)
    return destination


def _executer_ou_nettoyer(args, duree, sur_progression, arret, destination: Path) -> None:
    """Lance ffmpeg ; en cas d'annulation, supprime le fichier à moitié écrit."""
    try:
        ffmpeg.executer(args, duree_attendue=duree, sur_progression=sur_progression, arret=arret)
    except Annulation:
        destination.unlink(missing_ok=True)
        raise


def decalage_image_cle(source: str | Path, debut: float) -> float | None:
    """De combien de secondes le mode "rapide" démarrera-t-il avant `debut` ?

    Renvoie None si ffprobe manque. Utile pour prévenir l'utilisateur
    ("l'extrait rapide commencera 2,4 s avant le point demandé").
    """
    instants = ffmpeg.images_cles(source, limite=debut + 0.001)
    precedentes = [t for t in instants if t <= debut]
    if not precedentes:
        return None
    return debut - max(precedentes)


def decouper_flux(
    audio: Path,
    origine_audio: float,
    debut: float,
    fin: float,
    destination: str | Path,
    mode: Mode = "precis",
    video: Path | None = None,
    origine_video: float = 0.0,
    encodeur: str = ffmpeg.ENCODEUR_DEFAUT,
    sur_progression: ffmpeg.Progression | None = None,
    arret: Arret | None = None,
) -> Path:
    """Assemble et découpe des flux vidéo et audio séparés, déjà téléchargés.

    Les fichiers ne contiennent qu'un morceau de la vidéo d'origine : `origine_*`
    donne l'instant d'origine où chacun commence. Pour couper à `debut` dans la
    vidéo d'origine, on se place donc à `debut - origine` dans chaque fichier.
    (Voir segments.py : ces fichiers viennent du téléchargement par segments.)
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    duree_extrait = fin - debut

    args: list[str] = ["-y"]
    if video is not None and mode != "audio":
        # Une position de recherche (-ss) par entrée : chacune a sa propre origine.
        args += ["-ss", f"{max(0.0, debut - origine_video):.3f}", "-i", str(video)]
    args += ["-ss", f"{max(0.0, debut - origine_audio):.3f}", "-i", str(audio)]
    args += ["-t", f"{duree_extrait:.3f}"]

    if mode == "audio" or video is None:
        # AAC copié tel quel : aucune perte, et l'audio se coupe au paquet près (~20 ms).
        args += ["-map", "0:a:0", "-vn", "-c:a", "copy"]
    else:
        args += ["-map", "0:v:0", "-map", "1:a:0"]
        if mode == "rapide":
            # Comme decouper() : copie, la vidéo démarre sur l'image-clé précédente.
            args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            args += ffmpeg.args_encodage(encodeur)

    args += ["-movflags", "+faststart", str(destination)]
    _executer_ou_nettoyer(args, duree_extrait, sur_progression, arret, destination)
    return destination
